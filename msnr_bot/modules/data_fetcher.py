"""
Market Data Fetcher Module.

Fetches OHLC data for:
- Forex pairs (Major + Minor) via TwelveData API (direct)
- Metals (XAUUSD) via TwelveData API (direct)
- Crypto pairs via CCXT (OKX/Bybit/KuCoin) with PROXY support

Supports timeframes: M15, H1, H4

Note: In Indonesia, ISP blocks ALL crypto exchange APIs.
Set PROXY_URL in .env to route crypto requests through a proxy/VPN.
Forex data via TwelveData works without proxy.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import aiohttp
import pandas as pd
import numpy as np

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    ProxyConnector = None

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

# TwelveData API
TWELVEDATA_BASE = "https://api.twelvedata.com"

# Crypto exchanges to try (in priority order)
CRYPTO_EXCHANGES = ["okx", "bybit", "kucoin", "binance"]


class DataFetcher:
    """
    Fetches market data from multiple sources.

    - Crypto: CCXT with proxy (ISP blocks exchanges in Indonesia)
    - Forex/Metals: TwelveData API (direct connection, not blocked)
    """

    def __init__(self):
        self.twelvedata_key = Config.TWELVEDATA_API_KEY if hasattr(Config, 'TWELVEDATA_API_KEY') else ""
        self.proxy_url = Config.PROXY_URL if hasattr(Config, 'PROXY_URL') else ""
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._working_exchange: Optional[str] = None

        if self.proxy_url:
            logger.info(f"Proxy configured: {self.proxy_url}")
        else:
            logger.warning(
                "No PROXY_URL set. Crypto data may fail if ISP blocks exchanges. "
                "Set PROXY_URL in .env (e.g., http://127.0.0.1:7890 or socks5://127.0.0.1:1080)"
            )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (no proxy - for TwelveData)."""
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
    # CRYPTO DATA (CCXT with Proxy)
    # ─────────────────────────────────────────────

    async def _fetch_crypto(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """
        Fetch crypto data using CCXT with proxy support.
        Tries: OKX → Bybit → KuCoin → Binance
        """
        if ccxt_async is None:
            logger.error("CCXT not installed. Run: pip install ccxt")
            return None

        ccxt_tf = TIMEFRAME_MAP[timeframe]["ccxt"]
        ccxt_symbol = self._to_ccxt_symbol(symbol)

        # If we know which exchange works, try that first
        if self._working_exchange:
            df = await self._try_exchange(
                self._working_exchange, ccxt_symbol, ccxt_tf, num_candles
            )
            if df is not None:
                return df
            self._working_exchange = None

        # Try each exchange
        for exchange_id in CRYPTO_EXCHANGES:
            logger.info(f"Trying {exchange_id} for {symbol}...")
            df = await self._try_exchange(exchange_id, ccxt_symbol, ccxt_tf, num_candles)
            if df is not None:
                self._working_exchange = exchange_id
                logger.info(f"✓ Connected via {exchange_id}")
                return df

        logger.error(
            f"All exchanges failed for {symbol}. "
            f"{'Set PROXY_URL in .env!' if not self.proxy_url else 'Check your proxy connection.'}"
        )
        return None

    async def _try_exchange(
        self, exchange_id: str, ccxt_symbol: str, ccxt_tf: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """Try fetching from a specific exchange with proxy support."""
        exchange = None
        try:
            exchange_class = getattr(ccxt_async, exchange_id, None)
            if exchange_class is None:
                return None

            # Configure exchange
            config = {
                "enableRateLimit": True,
                "timeout": 15000,
                "options": {"defaultType": "spot"},
            }

            # Add proxy settings for blocked regions
            if self.proxy_url:
                if self.proxy_url.startswith("socks"):
                    config["socksProxy"] = self.proxy_url
                else:
                    config["httpProxy"] = self.proxy_url
                    config["httpsProxy"] = self.proxy_url

            exchange = exchange_class(config)

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
            logger.debug(f"{exchange_id} failed for {ccxt_symbol}: {e}")
            return None
        finally:
            if exchange:
                await exchange.close()

    # ─────────────────────────────────────────────
    # FOREX / METALS DATA (TwelveData - Direct)
    # ─────────────────────────────────────────────

    async def _fetch_forex(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """
        Fetch Forex/Metals data via TwelveData API.
        Direct connection (not blocked by ISP).
        """
        if self.twelvedata_key:
            df = await self._fetch_twelvedata(symbol, timeframe, num_candles)
            if df is not None:
                return df

        logger.warning(f"No data for {symbol} {timeframe}. Set TWELVEDATA_API_KEY in .env")
        return None

    async def _fetch_twelvedata(
        self, symbol: str, timeframe: str, num_candles: int
    ) -> Optional[pd.DataFrame]:
        """Fetch from TwelveData API."""
        try:
            session = await self._get_session()

            td_interval = self._to_twelvedata_interval(timeframe)
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
                    logger.error(f"TwelveData HTTP {resp.status} for {symbol}")
                    return None

                data = await resp.json()

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

                logger.info(f"✓ TwelveData: {symbol} {timeframe} ({len(df)} candles)")
                return df

        except aiohttp.ClientError as e:
            logger.error(f"TwelveData connection error for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"TwelveData error for {symbol}: {e}")
            return None

    # ─────────────────────────────────────────────
    # CACHE MANAGEMENT
    # ─────────────────────────────────────────────

    def _is_cache_valid(self, cache_key: str, timeframe: str) -> bool:
        """Check if cached data is still valid."""
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

    def _to_ccxt_symbol(self, symbol: str) -> str:
        """Convert symbol to CCXT format (e.g., BTCUSDT -> BTC/USDT)."""
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USDT"
        elif symbol.endswith("USD"):
            base = symbol[:-3]
            return f"{base}/USD"
        return f"{symbol[:3]}/{symbol[3:]}"

    def _to_twelvedata_symbol(self, symbol: str) -> str:
        """Convert symbol to TwelveData format."""
        if symbol == "XAUUSD":
            return "XAU/USD"
        if symbol.endswith("USDT"):
            return f"{symbol[:-4]}/{symbol[-4:]}"
        return f"{symbol[:3]}/{symbol[3:]}"

    def _to_twelvedata_interval(self, timeframe: str) -> str:
        """Convert timeframe to TwelveData interval."""
        mapping = {"M15": "15min", "H1": "1h", "H4": "4h"}
        return mapping.get(timeframe, "1h")

    # ─────────────────────────────────────────────
    # UTILITY
    # ─────────────────────────────────────────────

    def get_current_price(self, df: pd.DataFrame) -> float:
        """Get the most recent close price."""
        if df is not None and len(df) > 0:
            return float(df.iloc[-1]["close"])
        return 0.0
