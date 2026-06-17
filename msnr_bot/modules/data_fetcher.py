"""
Market Data Fetcher Module.

Fetches OHLC data for ALL markets via TwelveData API:
- Forex pairs (Major + Minor)
- Metals (XAUUSD)
- Crypto pairs (BTC, ETH, SOL, etc.)

All data goes through TwelveData which is NOT blocked by ISP.
No proxy/VPN needed!

Supports timeframes: M15, H1, H4
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

# Timeframe mapping
TIMEFRAME_MAP = {
    "M15": {"interval": "15min", "seconds": 900},
    "H1": {"interval": "1h", "seconds": 3600},
    "H4": {"interval": "4h", "seconds": 14400},
}

# TwelveData API
TWELVEDATA_BASE = "https://api.twelvedata.com"


class DataFetcher:
    """
    Fetches market data from TwelveData API for ALL instruments.

    TwelveData supports Forex, Metals, AND Crypto — all from one API.
    Not blocked by Indonesian ISP (confirmed working).

    Free tier: 800 requests/day, 8 requests/minute.
    """

    def __init__(self):
        self.api_key = Config.TWELVEDATA_API_KEY if hasattr(Config, 'TWELVEDATA_API_KEY') else ""
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_count = 0

        if not self.api_key:
            logger.error(
                "TWELVEDATA_API_KEY not set! Get your free key at https://twelvedata.com"
            )
        else:
            logger.info("TwelveData API configured. All data will be fetched via TwelveData.")

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
    # PUBLIC API
    # ─────────────────────────────────────────────

    async def fetch_ohlc(
        self, symbol: str, timeframe: str, num_candles: int = 300
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLC data for a symbol and timeframe.
        Returns DataFrame with columns: open, high, low, close, volume, timestamp
        """
        cache_key = f"{symbol}_{timeframe}"

        # Check cache
        if self._is_cache_valid(cache_key, timeframe):
            return self._cache[cache_key]

        if not self.api_key:
            logger.error("No API key. Set TWELVEDATA_API_KEY in .env")
            return None

        try:
            df = await self._fetch_twelvedata(symbol, timeframe, num_candles)

            if df is not None and len(df) > 0:
                self._cache[cache_key] = df
                self._cache_expiry[cache_key] = datetime.utcnow()
                return df

        except Exception as e:
            logger.error(f"Error fetching {symbol} {timeframe}: {e}")

        return None

    async def fetch_multi_timeframe(
        self, symbol: str
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch all timeframes for a symbol."""
        results = {}
        for tf in Config.TIMEFRAMES:
            results[tf] = await self.fetch_ohlc(symbol, tf)
            # Rate limit: small delay between requests
            await asyncio.sleep(0.5)
        return results

    async def fetch_batch(
        self, symbols: List[str], timeframe: str
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch data for multiple symbols on same timeframe."""
        results = {}

        # TwelveData rate limit: 8 req/min on free tier
        # Process carefully with delays
        batch_size = 7  # Keep under 8/min limit
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]

            for sym in batch:
                df = await self.fetch_ohlc(sym, timeframe)
                results[sym] = df
                # 8 req/min = 1 req per 7.5 seconds (be safe)
                await asyncio.sleep(8)

            logger.info(
                f"Batch progress: {min(i + batch_size, len(symbols))}/{len(symbols)} symbols"
            )

        return results

    # ─────────────────────────────────────────────
    # TWELVEDATA API
    # ─────────────────────────────────────────────

    async def _fetch_twelvedata(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """Fetch from TwelveData API. Works for Forex, Metals, AND Crypto."""
        try:
            session = await self._get_session()

            td_interval = TIMEFRAME_MAP[timeframe]["interval"]
            td_symbol = self._to_twelvedata_symbol(symbol)

            params = {
                "symbol": td_symbol,
                "interval": td_interval,
                "outputsize": min(num_candles, 800),  # TwelveData max per request
                "apikey": self.api_key,
                "format": "JSON",
            }

            async with session.get(
                f"{TWELVEDATA_BASE}/time_series", params=params
            ) as resp:
                self._request_count += 1

                if resp.status != 200:
                    logger.error(f"TwelveData HTTP {resp.status} for {symbol}")
                    return None

                data = await resp.json()

                # Check for API errors
                if "code" in data and data["code"] != 200:
                    error_msg = data.get("message", "Unknown error")
                    logger.error(f"TwelveData API error for {symbol}: {error_msg}")
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

                logger.info(f"✓ {symbol} {timeframe} ({len(df)} candles)")
                return df

        except aiohttp.ClientError as e:
            logger.error(f"Connection error for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return None

    # ─────────────────────────────────────────────
    # CACHE MANAGEMENT
    # ─────────────────────────────────────────────

    def _is_cache_valid(self, cache_key: str, timeframe: str) -> bool:
        """Check if cached data is still valid (half candle period)."""
        if cache_key not in self._cache or cache_key not in self._cache_expiry:
            return False

        seconds = TIMEFRAME_MAP[timeframe]["seconds"]
        expiry_seconds = seconds / 2

        elapsed = (datetime.utcnow() - self._cache_expiry[cache_key]).total_seconds()
        return elapsed < expiry_seconds

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        self._cache_expiry.clear()

    # ─────────────────────────────────────────────
    # SYMBOL CONVERSION
    # ─────────────────────────────────────────────

    def _to_twelvedata_symbol(self, symbol: str) -> str:
        """
        Convert internal symbol to TwelveData format.

        Forex:  EURUSD  → EUR/USD
        Metals: XAUUSD  → XAU/USD
        Crypto: BTCUSDT → BTC/USD  (TwelveData uses /USD for crypto)
        """
        if symbol == "XAUUSD":
            return "XAU/USD"

        # Crypto pairs: TwelveData uses BTC/USD format
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USD"

        # Forex pairs: EURUSD → EUR/USD
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
        """Total API requests made this session."""
        return self._request_count
