"""
Market Data Fetcher Module — RATE-LIMIT OPTIMIZED.

Uses requests library (not aiohttp) for maximum Windows compatibility.
aiohttp has known SSL/DNS issues on certain Windows configurations.

TwelveData Free Tier: 800 requests/day, 8 requests/minute.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

import requests
import pandas as pd
import numpy as np

from msnr_bot.config import Config

logger = logging.getLogger(__name__)

# Timeframe config with cache duration
TIMEFRAME_MAP = {
    "M15": {"interval": "15min", "seconds": 900, "cache_seconds": 900},
    "H1": {"interval": "1h", "seconds": 3600, "cache_seconds": 3600},
    "H4": {"interval": "4h", "seconds": 14400, "cache_seconds": 14400},
}

TWELVEDATA_BASE = "https://api.twelvedata.com"
DAILY_REQUEST_LIMIT = 780


class DataFetcher:
    """
    Rate-limit optimized data fetcher using TwelveData API.
    Uses requests (not aiohttp) for Windows DNS/SSL compatibility.
    """

    def __init__(self):
        self.api_key = Config.TWELVEDATA_API_KEY if hasattr(Config, 'TWELVEDATA_API_KEY') else ""
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        self._request_count = 0
        self._daily_count = 0
        self._day_start = datetime.utcnow().date()
        self._last_request_time: float = 0
        self._executor = ThreadPoolExecutor(max_workers=2)

        if not self.api_key:
            logger.error(
                "TWELVEDATA_API_KEY not set! Get free key: https://twelvedata.com "
                "Make sure .env file is in the same folder as main.py"
            )
        else:
            logger.info(f"TwelveData API ready (key: {self.api_key[:8]}...) | Budget: {DAILY_REQUEST_LIMIT}/day")

    async def close(self):
        """Cleanup."""
        self._executor.shutdown(wait=False)

    # ─────────────────────────────────────────────
    # RATE LIMITING
    # ─────────────────────────────────────────────

    def _reset_daily_counter(self):
        """Reset daily counter if new day."""
        today = datetime.utcnow().date()
        if today != self._day_start:
            self._daily_count = 0
            self._day_start = today
            logger.info("Daily request counter reset.")

    def _can_make_request(self) -> bool:
        """Check if we can make another request."""
        self._reset_daily_counter()
        return self._daily_count < DAILY_REQUEST_LIMIT

    async def _rate_limit_wait(self):
        """Wait to respect 8 req/min rate limit."""
        now = time.time()
        elapsed = now - self._last_request_time
        min_interval = 8.0  # 8 req/min = 1 every 7.5s, use 8 to be safe
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

        # Check cache FIRST
        if self._is_cache_valid(cache_key, timeframe):
            return self._cache[cache_key]

        # Check budget
        if not self._can_make_request():
            logger.warning(f"Daily limit reached ({DAILY_REQUEST_LIMIT}). Using stale cache.")
            if cache_key in self._cache:
                return self._cache[cache_key]
            return None

        if not self.api_key:
            logger.error("NO API KEY! Set TWELVEDATA_API_KEY in .env file")
            return None

        try:
            # Rate limit
            await self._rate_limit_wait()

            # Run the blocking HTTP request in a thread pool
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                self._executor,
                self._fetch_twelvedata_sync,
                symbol, timeframe, num_candles
            )

            if df is not None and len(df) > 0:
                self._cache[cache_key] = df
                self._cache_expiry[cache_key] = datetime.utcnow()
                return df

        except Exception as e:
            logger.error(f"Error fetching {symbol} {timeframe}: {e}")

        return None

    async def fetch_multi_timeframe(self, symbol: str) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch all timeframes for a single symbol. Cost: 3 requests."""
        results = {}
        for tf in Config.TIMEFRAMES:
            results[tf] = await self.fetch_ohlc(symbol, tf)
        return results

    async def fetch_batch(
        self, symbols: List[str], timeframe: str
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch data for a list of symbols, respecting rate limits."""
        results = {}

        for sym in symbols:
            if not self._can_make_request():
                logger.warning("Budget exhausted. Skipping remaining symbols.")
                break

            df = await self.fetch_ohlc(sym, timeframe)
            results[sym] = df

        logger.info(f"Fetched {len(results)} symbols. {self.get_cache_stats()}")
        return results

    # ─────────────────────────────────────────────
    # TWELVEDATA API (Synchronous - runs in thread pool)
    # ─────────────────────────────────────────────

    def _fetch_twelvedata_sync(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """
        Fetch from TwelveData API using requests library.
        This runs in a thread pool to avoid blocking the event loop.
        """
        try:
            td_interval = TIMEFRAME_MAP[timeframe]["interval"]
            td_symbol = self._to_twelvedata_symbol(symbol)

            params = {
                "symbol": td_symbol,
                "interval": td_interval,
                "outputsize": min(num_candles, 500),
                "apikey": self.api_key,
                "format": "JSON",
            }

            resp = requests.get(
                f"{TWELVEDATA_BASE}/time_series",
                params=params,
                timeout=30,
            )

            self._request_count += 1
            self._daily_count += 1
            self._last_request_time = time.time()

            if resp.status_code != 200:
                logger.error(f"HTTP {resp.status_code} for {symbol}")
                return None

            data = resp.json()

            # Check for API errors
            if "code" in data and data["code"] != 200:
                error_msg = data.get("message", "Unknown error")
                if "limit" in error_msg.lower():
                    logger.error(f"RATE LIMIT HIT: {error_msg}")
                else:
                    logger.error(f"API error for {symbol}: {error_msg}")
                return None

            if "values" not in data:
                if "message" in data:
                    logger.error(f"TwelveData error for {symbol}: {data['message']}")
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

            logger.info(f"[OK] {symbol} {timeframe} ({len(df)} candles) [req #{self._daily_count}]")
            return df

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error for {symbol}: {e}")
            return None
        except requests.exceptions.Timeout:
            logger.error(f"Timeout for {symbol}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return None

    # ─────────────────────────────────────────────
    # CACHE MANAGEMENT
    # ─────────────────────────────────────────────

    def _is_cache_valid(self, cache_key: str, timeframe: str) -> bool:
        """Check if cached data is still valid (full candle period)."""
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
            f"Cache: {cached} items | "
            f"Today: {self._daily_count}/{DAILY_REQUEST_LIMIT} requests | "
            f"Remaining: {self.remaining_budget}"
        )

    # ─────────────────────────────────────────────
    # SYMBOL CONVERSION
    # ─────────────────────────────────────────────

    def _to_twelvedata_symbol(self, symbol: str) -> str:
        """
        Convert internal symbol to TwelveData format.
        Forex:  EURUSD  -> EUR/USD
        Metals: XAUUSD  -> XAU/USD
        Crypto: BTCUSDT -> BTC/USD
        """
        if symbol == "XAUUSD":
            return "XAU/USD"

        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USD"

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
