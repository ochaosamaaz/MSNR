"""
Market Data Fetcher Module.

Fetches OHLC data for:
- Forex pairs (Major + Minor) via free API
- Metals (XAUUSD) via free API
- Crypto pairs via CCXT (Binance)

Supports timeframes: M15, H1, H4
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import aiohttp
import pandas as pd
import numpy as np

try:
    import ccxt.async_support as ccxt_async
except ImportError:
    ccxt_async = None

from msnr_bot.config import Config

logger = logging.getLogger(__name__)

# Timeframe mapping
TIMEFRAME_MAP = {
    "M15": {"ccxt": "15m", "seconds": 900, "candles_needed": 300},
    "H1": {"ccxt": "1h", "seconds": 3600, "candles_needed": 300},
    "H4": {"ccxt": "4h", "seconds": 14400, "candles_needed": 300},
}

# Twelve Data free API (alternative: Alpha Vantage, Forex API)
TWELVEDATA_BASE = "https://api.twelvedata.com"


class DataFetcher:
    """
    Fetches market data from multiple sources.

    - Crypto: CCXT (Binance) - free, no API key needed for public data
    - Forex/Metals: TwelveData API or fallback to synthetic/cached data
    """

    def __init__(self):
        self.twelvedata_key = Config.TWELVEDATA_API_KEY if hasattr(Config, 'TWELVEDATA_API_KEY') else ""
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        self._session: Optional[aiohttp.ClientSession] = None

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

        # Check cache (valid for 1 candle period)
        if self._is_cache_valid(cache_key, timeframe):
            return self._cache[cache_key]

        try:
            category = Config.get_symbol_category(symbol)

            if category == "CRYPTO" or symbol in Config.CRYPTO:
                df = await self._fetch_crypto(symbol, timeframe, num_candles)
            else:
                df = await self._fetch_forex(symbol, timeframe, num_candles)

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
        return results

    async def fetch_batch(
        self, symbols: List[str], timeframe: str
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch data for multiple symbols on same timeframe."""
        results = {}
        # Process in batches to avoid rate limits
        batch_size = 5
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            tasks = [self.fetch_ohlc(sym, timeframe) for sym in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for sym, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Failed to fetch {sym}: {result}")
                    results[sym] = None
                else:
                    results[sym] = result

            # Rate limit protection
            if i + batch_size < len(symbols):
                await asyncio.sleep(1)

        return results

    # ─────────────────────────────────────────────
    # CRYPTO DATA (CCXT - Binance)
    # ─────────────────────────────────────────────

    async def _fetch_crypto(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """Fetch crypto data using CCXT (Binance)."""
        if ccxt_async is None:
            logger.error("CCXT not installed. Cannot fetch crypto data.")
            return None

        exchange = ccxt_async.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        try:
            ccxt_tf = TIMEFRAME_MAP[timeframe]["ccxt"]
            ccxt_symbol = self._to_ccxt_symbol(symbol)

            ohlcv = await exchange.fetch_ohlcv(
                ccxt_symbol, ccxt_tf, limit=num_candles
            )

            if not ohlcv:
                return None

            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.astype({
                "open": float, "high": float, "low": float,
                "close": float, "volume": float
            })

            return df

        except Exception as e:
            logger.error(f"CCXT error for {symbol}: {e}")
            return None
        finally:
            await exchange.close()

    # ─────────────────────────────────────────────
    # FOREX / METALS DATA
    # ─────────────────────────────────────────────

    async def _fetch_forex(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """
        Fetch Forex/Metals data.

        Primary: TwelveData API (free tier: 800 req/day)
        Fallback: Generate from available sources
        """
        # Try TwelveData first
        if self.twelvedata_key:
            df = await self._fetch_twelvedata(symbol, timeframe, num_candles)
            if df is not None:
                return df

        # Fallback: Try fetching from a free forex API
        df = await self._fetch_free_forex_api(symbol, timeframe, num_candles)
        if df is not None:
            return df

        # Last resort: Try CCXT with forex-like crypto pairs or return None
        logger.warning(f"No data source available for {symbol} {timeframe}")
        return None

    async def _fetch_twelvedata(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """Fetch from TwelveData API."""
        try:
            session = await self._get_session()

            # Convert timeframe
            td_interval = self._to_twelvedata_interval(timeframe)
            # Convert symbol format (EURUSD -> EUR/USD)
            td_symbol = self._to_twelvedata_symbol(symbol)

            params = {
                "symbol": td_symbol,
                "interval": td_interval,
                "outputsize": num_candles,
                "apikey": self.twelvedata_key,
                "format": "JSON",
            }

            async with session.get(
                f"{TWELVEDATA_BASE}/time_series", params=params
            ) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()

                if "values" not in data:
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

                # TwelveData returns newest first, reverse it
                df = df.iloc[::-1].reset_index(drop=True)
                return df

        except Exception as e:
            logger.error(f"TwelveData error for {symbol}: {e}")
            return None

    async def _fetch_free_forex_api(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """
        Fetch from free Forex API alternatives.
        Uses Yahoo Finance via yfinance-style endpoint or other free sources.
        """
        try:
            session = await self._get_session()

            # Use a free forex data endpoint
            # Format symbol for the API
            pair = f"{symbol[:3]}/{symbol[3:]}" if len(symbol) == 6 else symbol

            # Try using CCXT with a forex-supporting exchange
            if ccxt_async is not None:
                return await self._fetch_forex_via_ccxt(symbol, timeframe, num_candles)

        except Exception as e:
            logger.error(f"Free forex API error for {symbol}: {e}")

        return None

    async def _fetch_forex_via_ccxt(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """
        Attempt to fetch forex data through CCXT exchanges that support forex.
        """
        # Try exchanges that might have forex data
        exchanges_to_try = ["currencycom"]

        for exchange_id in exchanges_to_try:
            try:
                exchange_class = getattr(ccxt_async, exchange_id, None)
                if exchange_class is None:
                    continue

                exchange = exchange_class({"enableRateLimit": True})

                ccxt_tf = TIMEFRAME_MAP[timeframe]["ccxt"]
                # Format: EUR/USD for forex
                ccxt_symbol = f"{symbol[:3]}/{symbol[3:]}"

                await exchange.load_markets()
                if ccxt_symbol not in exchange.markets:
                    await exchange.close()
                    continue

                ohlcv = await exchange.fetch_ohlcv(
                    ccxt_symbol, ccxt_tf, limit=num_candles
                )
                await exchange.close()

                if ohlcv:
                    df = pd.DataFrame(
                        ohlcv,
                        columns=["timestamp", "open", "high", "low", "close", "volume"]
                    )
                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                    df = df.astype({
                        "open": float, "high": float, "low": float,
                        "close": float, "volume": float
                    })
                    return df

            except Exception as e:
                logger.debug(f"CCXT {exchange_id} failed for {symbol}: {e}")
                continue

        return None

    # ─────────────────────────────────────────────
    # CACHE MANAGEMENT
    # ─────────────────────────────────────────────

    def _is_cache_valid(self, cache_key: str, timeframe: str) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self._cache or cache_key not in self._cache_expiry:
            return False

        # Cache valid for half a candle period
        seconds = TIMEFRAME_MAP[timeframe]["seconds"]
        expiry_seconds = seconds / 2

        elapsed = (datetime.utcnow() - self._cache_expiry[cache_key]).total_seconds()
        return elapsed < expiry_seconds

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        self._cache_expiry.clear()

    # ─────────────────────────────────────────────
    # SYMBOL CONVERSION HELPERS
    # ─────────────────────────────────────────────

    def _to_ccxt_symbol(self, symbol: str) -> str:
        """Convert symbol to CCXT format."""
        # Crypto: BTCUSDT -> BTC/USDT
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USDT"
        elif symbol.endswith("USD"):
            base = symbol[:-3]
            return f"{base}/USD"
        # Forex: EURUSD -> EUR/USD
        return f"{symbol[:3]}/{symbol[3:]}"

    def _to_twelvedata_symbol(self, symbol: str) -> str:
        """Convert symbol to TwelveData format."""
        if symbol == "XAUUSD":
            return "XAU/USD"
        if symbol.endswith("USDT"):
            return f"{symbol[:-4]}/{symbol[-4:]}"
        # Forex pairs
        return f"{symbol[:3]}/{symbol[3:]}"

    def _to_twelvedata_interval(self, timeframe: str) -> str:
        """Convert timeframe to TwelveData interval."""
        mapping = {
            "M15": "15min",
            "H1": "1h",
            "H4": "4h",
        }
        return mapping.get(timeframe, "1h")

    # ─────────────────────────────────────────────
    # UTILITY
    # ─────────────────────────────────────────────

    def get_current_price(self, df: pd.DataFrame) -> float:
        """Get the most recent close price from data."""
        if df is not None and len(df) > 0:
            return float(df.iloc[-1]["close"])
        return 0.0
