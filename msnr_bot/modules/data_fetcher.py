"""
Market Data Fetcher Module — RATE-LIMIT OPTIMIZED.

TwelveData Free Tier: 800 requests/day, 8 requests/minute.

Optimization strategies:
1. Aggressive caching — M15: 15min, H1: 1hr, H4: 4hr
2. Priority scanning — Tier 1 (12 symbols) first, Tier 2 only when needed
3. Smart rate limiting — respects 8 req/min, tracks daily usage
4. H4 fetched ONCE per day (zones rarely change)
5. Single-symbol /pair command uses only 3 requests (one per timeframe)

Budget breakdown:
- Auto scan (Tier 1 only): 12 symbols × 1 TF = 12 requests per scan
- Full /scan command: 12 symbols × 3 TF = 36 requests
- /pair SYMBOL: 3 requests
- Daily budget: ~22 auto scans or 7 full scans
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp
import pandas as pd
import numpy as np

from msnr_bot.config import Config

logger = logging.getLogger(__name__)

# Timeframe config with cache duration
TIMEFRAME_MAP = {
    "M15": {"interval": "15min", "seconds": 900, "cache_seconds": 900},     # cache 15 min
    "H1": {"interval": "1h", "seconds": 3600, "cache_seconds": 3600},       # cache 1 hour
    "H4": {"interval": "4h", "seconds": 14400, "cache_seconds": 14400},     # cache 4 hours
}

TWELVEDATA_BASE = "https://api.twelvedata.com"

# Daily request budget
DAILY_REQUEST_LIMIT = 780  # Leave 20 buffer from 800


class DataFetcher:
    """
    Rate-limit optimized data fetcher using TwelveData API.

    Free tier: 800 req/day, 8 req/min.
    Uses aggressive caching to minimize API calls.
    """

    def __init__(self):
        self.api_key = Config.TWELVEDATA_API_KEY if hasattr(Config, 'TWELVEDATA_API_KEY') else ""
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_count = 0
        self._daily_count = 0
        self._day_start = datetime.utcnow().date()
        self._last_request_time: Optional[datetime] = None

        if not self.api_key:
            logger.error("⚠️ TWELVEDATA_API_KEY not set! Get free key: https://twelvedata.com")
        else:
            logger.info(f"✓ TwelveData API ready (daily budget: {DAILY_REQUEST_LIMIT} requests)")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self):
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()

    # ─────────────────────────────────────────────
    # RATE LIMITING
    # ─────────────────────────────────────────────

    def _reset_daily_counter(self):
        """Reset daily counter if new day."""
        today = datetime.utcnow().date()
        if today != self._day_start:
            self._daily_count = 0
            self._day_start = today
            logger.info("📊 Daily request counter reset.")

    def _can_make_request(self) -> bool:
        """Check if we can make another request."""
        self._reset_daily_counter()
        return self._daily_count < DAILY_REQUEST_LIMIT

    async def _rate_limit_wait(self):
        """Wait to respect 8 req/min rate limit."""
        if self._last_request_time:
            elapsed = (datetime.utcnow() - self._last_request_time).total_seconds()
            # 8 req/min = 1 request every 7.5 seconds minimum
            min_interval = 8.0
            if elapsed < min_interval:
                wait_time = min_interval - elapsed
                await asyncio.sleep(wait_time)

    @property
    def remaining_budget(self) -> int:
        """Remaining daily request budget."""
        self._reset_daily_counter()
        return max(0, DAILY_REQUEST_LIMIT - self._daily_count)

    # ─────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────

    async def fetch_ohlc(
        self, symbol: str, timeframe: str, num_candles: int = 200
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLC data for a symbol and timeframe.
        Uses cache aggressively. Only hits API if cache expired.
        """
        cache_key = f"{symbol}_{timeframe}"

        # Check cache FIRST (saves API calls!)
        if self._is_cache_valid(cache_key, timeframe):
            return self._cache[cache_key]

        # Check budget
        if not self._can_make_request():
            logger.warning(f"⚠️ Daily limit reached ({DAILY_REQUEST_LIMIT}). Using stale cache or skipping.")
            # Return stale cache if available
            if cache_key in self._cache:
                return self._cache[cache_key]
            return None

        if not self.api_key:
            return None

        try:
            # Rate limit
            await self._rate_limit_wait()

            df = await self._fetch_twelvedata(symbol, timeframe, num_candles)

            if df is not None and len(df) > 0:
                self._cache[cache_key] = df
                self._cache_expiry[cache_key] = datetime.utcnow()
                return df

        except Exception as e:
            logger.error(f"Error fetching {symbol} {timeframe}: {e}")

        return None

    async def fetch_priority_scan(self, timeframe: str = "H1") -> Dict[str, Optional[pd.DataFrame]]:
        """
        Fetch Tier 1 priority symbols only (12 symbols).
        Cost: 12 requests. Used for auto-scan.
        """
        symbols = Config.priority_symbols()
        logger.info(f"📡 Priority scan: {len(symbols)} symbols on {timeframe} (budget: {self.remaining_budget})")
        return await self._fetch_symbols(symbols, timeframe)

    async def fetch_full_scan(self, timeframe: str) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Fetch ALL symbols on a timeframe.
        Cost: ~35 requests. Used for manual /scan command.
        """
        symbols = Config.all_symbols()
        logger.info(f"📡 Full scan: {len(symbols)} symbols on {timeframe} (budget: {self.remaining_budget})")
        return await self._fetch_symbols(symbols, timeframe)

    async def fetch_multi_timeframe(self, symbol: str) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Fetch all timeframes for a single symbol.
        Cost: 3 requests. Used for /pair command.
        """
        results = {}
        for tf in Config.TIMEFRAMES:
            results[tf] = await self.fetch_ohlc(symbol, tf)
        return results

    async def _fetch_symbols(
        self, symbols: List[str], timeframe: str
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch data for a list of symbols, respecting rate limits."""
        results = {}

        for sym in symbols:
            # Skip if no budget left
            if not self._can_make_request():
                logger.warning(f"⚠️ Budget exhausted. Skipping remaining symbols.")
                break

            df = await self.fetch_ohlc(sym, timeframe)
            results[sym] = df

        logger.info(f"📊 Fetched {len(results)} symbols. Budget remaining: {self.remaining_budget}")
        return results

    # Kept for backward compatibility with scanner
    async def fetch_batch(
        self, symbols: List[str], timeframe: str
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch data for multiple symbols (alias for _fetch_symbols)."""
        return await self._fetch_symbols(symbols, timeframe)

    # ─────────────────────────────────────────────
    # TWELVEDATA API
    # ─────────────────────────────────────────────

    async def _fetch_twelvedata(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """Fetch from TwelveData API."""
        try:
            session = await self._get_session()

            td_interval = TIMEFRAME_MAP[timeframe]["interval"]
            td_symbol = self._to_twelvedata_symbol(symbol)

            params = {
                "symbol": td_symbol,
                "interval": td_interval,
                "outputsize": min(num_candles, 500),  # Don't request too much
                "apikey": self.api_key,
                "format": "JSON",
            }

            async with session.get(
                f"{TWELVEDATA_BASE}/time_series", params=params
            ) as resp:
                self._request_count += 1
                self._daily_count += 1
                self._last_request_time = datetime.utcnow()

                if resp.status != 200:
                    logger.error(f"HTTP {resp.status} for {symbol}")
                    return None

                data = await resp.json()

                # Check for API errors
                if "code" in data and data["code"] != 200:
                    error_msg = data.get("message", "Unknown error")
                    if "limit" in error_msg.lower():
                        logger.error(f"⚠️ RATE LIMIT HIT: {error_msg}")
                    else:
                        logger.error(f"API error for {symbol}: {error_msg}")
                    return None

                if "values" not in data:
                    if "message" in data:
                        logger.error(f"TwelveData: {data['message']}")
                    return None

                values = data["values"]
                df = pd.DataFrame(values)
                df = df.rename(columns={
                    "datetime": "timestamp",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                })
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.astype({
                    "open": float, "high": float, "low": float,
                    "close": float,
                })
                if "volume" in df.columns:
                    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
                else:
                    df["volume"] = 0.0

                # TwelveData returns newest first, reverse
                df = df.iloc[::-1].reset_index(drop=True)

                logger.info(f"✓ {symbol} {timeframe} ({len(df)} candles) [req #{self._daily_count}]")
                return df

        except aiohttp.ClientError as e:
            logger.error(f"Connection error for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return None

    # ─────────────────────────────────────────────
    # CACHE MANAGEMENT (Aggressive)
    # ─────────────────────────────────────────────

    def _is_cache_valid(self, cache_key: str, timeframe: str) -> bool:
        """
        Check if cached data is still valid.
        Cache duration = FULL candle period (not half).
        M15 → 15 min, H1 → 1 hour, H4 → 4 hours.
        """
        if cache_key not in self._cache or cache_key not in self._cache_expiry:
            return False

        cache_seconds = TIMEFRAME_MAP[timeframe]["cache_seconds"]
        elapsed = (datetime.utcnow() - self._cache_expiry[cache_key]).total_seconds()
        return elapsed < cache_seconds

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        self._cache_expiry.clear()

    def get_cache_stats(self) -> str:
        """Get cache statistics."""
        cached = len(self._cache)
        return (
            f"📦 Cache: {cached} items | "
            f"📊 Today: {self._daily_count}/{DAILY_REQUEST_LIMIT} requests | "
            f"💰 Remaining: {self.remaining_budget}"
        )

    # ─────────────────────────────────────────────
    # SYMBOL CONVERSION
    # ─────────────────────────────────────────────

    def _to_twelvedata_symbol(self, symbol: str) -> str:
        """
        Convert internal symbol to TwelveData format.

        Forex:  EURUSD  → EUR/USD
        Metals: XAUUSD  → XAU/USD
        Crypto: BTCUSDT → BTC/USD
        """
        if symbol == "XAUUSD":
            return "XAU/USD"

        # Crypto: BTCUSDT → BTC/USD
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USD"

        # Forex: EURUSD → EUR/USD
        if len(symbol) == 6:
            return f"{symbol[:3]}/{symbol[3:]}"

        return symbol

    # ─────────────────────────────────────────────
    # UTILITY
    # ─────────────────────────────────────────────

    def get_current_price(self, df: pd.DataFrame) -> float:
        """Get the most recent close price."""
        if df is not None and len(df) > 0:
            return float(df.iloc[-1]["close"])
        return 0.0

    @property
    def requests_made(self) -> int:
        """Total API requests this session."""
        return self._request_count
