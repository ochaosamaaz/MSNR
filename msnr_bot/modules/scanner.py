"""
Market Scanner Module.

Orchestrates the full scanning process:
1. Fetch market data for all symbols/timeframes
2. Detect SNR zones
3. Run confluence analysis
4. Score setups
5. Calculate trade parameters
6. Filter and return valid setups
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from msnr_bot.config import Config
from msnr_bot.core.snr_engine import SNREngine, SNRZone, ZoneType, ZoneClassification
from msnr_bot.core.confluence import ConfluenceDetector, ConfluenceResult, TrendDirection
from msnr_bot.core.scoring import ScoringEngine, ScoreBreakdown, Grade, SetupType
from msnr_bot.core.trade_setup import TradeCalculator, TradeSetup, TradeDirection
from msnr_bot.modules.data_fetcher import DataFetcher

logger = logging.getLogger(__name__)


class ScanResult:
    """Results from a market scan."""

    def __init__(self):
        self.all_setups: List[TradeSetup] = []
        self.valid_setups: List[TradeSetup] = []
        self.sniper_setups: List[TradeSetup] = []
        self.high_probability_setups: List[TradeSetup] = []
        self.watchlist_setups: List[TradeSetup] = []
        self.fresh_zones: List[SNRZone] = []
        self.non_fresh_zones: List[SNRZone] = []
        self.all_zones: List[SNRZone] = []
        self.scan_time: datetime = datetime.utcnow()
        self.symbols_scanned: int = 0
        self.errors: List[str] = []

    def summary(self) -> str:
        """Get scan summary."""
        return (
            f"📊 Scan Complete\n"
            f"⏰ {self.scan_time.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"🔍 Symbols Scanned: {self.symbols_scanned}\n"
            f"📍 Total Zones: {len(self.all_zones)}\n"
            f"✅ Valid Setups: {len(self.valid_setups)}\n"
            f"🎯 Sniper Setups: {len(self.sniper_setups)}\n"
            f"⚡ High Probability: {len(self.high_probability_setups)}\n"
            f"👀 Watchlist (A/A+): {len(self.watchlist_setups)}\n"
            f"🟢 Fresh Zones: {len(self.fresh_zones)}\n"
            f"🟡 Non-Fresh Zones: {len(self.non_fresh_zones)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 Tip: Use /pair SYMBOL for detailed analysis"
        )


class MarketScanner:
    """
    Main scanner that orchestrates the full MSNR analysis pipeline.
    """

    def __init__(self):
        self.snr_engine = SNREngine()
        self.confluence_detector = ConfluenceDetector()
        self.scoring_engine = ScoringEngine()
        self.trade_calculator = TradeCalculator()
        self.data_fetcher = DataFetcher()
        self._last_scan_result: Optional[ScanResult] = None

    async def scan_all(self) -> ScanResult:
        """
        Smart scan — uses priority symbols on H1 to save API budget.
        Full scan (all symbols × all timeframes) only when explicitly requested.
        Cost: ~12 requests (priority) vs 105 requests (full).
        """
        result = ScanResult()
        symbols = Config.priority_symbols()

        logger.info(
            f"Starting priority scan: {len(symbols)} symbols | "
            f"Budget: {self.data_fetcher.remaining_budget} requests remaining"
        )

        # Scan H1 first (best balance of signal quality vs API cost)
        timeframe = "H1"
        data_batch = await self.data_fetcher.fetch_batch(symbols, timeframe)

        for symbol, df in data_batch.items():
            if df is None or len(df) < 50:
                continue

            try:
                setups, zones = await self._analyze_symbol(
                    symbol, timeframe, df, data_batch
                )
                result.all_setups.extend(setups)
                result.all_zones.extend(zones)
                result.symbols_scanned += 1
            except Exception as e:
                error_msg = f"Error analyzing {symbol} {timeframe}: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        # Categorize results
        self._categorize_results(result)
        result.scan_time = datetime.utcnow()
        self._last_scan_result = result

        logger.info(
            f"Scan complete: {len(result.valid_setups)} valid setups | "
            f"{self.data_fetcher.get_cache_stats()}"
        )
        return result

    async def scan_full(self) -> ScanResult:
        """
        Full scan — ALL symbols × ALL timeframes.
        Expensive: ~105 requests. Only use when user explicitly wants full scan.
        """
        result = ScanResult()
        all_symbols = Config.all_symbols()

        logger.info(f"Starting full market scan: {len(all_symbols)} symbols")

        for timeframe in Config.TIMEFRAMES:
            logger.info(f"Scanning timeframe: {timeframe}")

            # Fetch data in batches
            data_batch = await self.data_fetcher.fetch_batch(all_symbols, timeframe)

            for symbol, df in data_batch.items():
                if df is None or len(df) < 50:
                    continue

                try:
                    setups, zones = await self._analyze_symbol(
                        symbol, timeframe, df, data_batch
                    )
                    result.all_setups.extend(setups)
                    result.all_zones.extend(zones)
                    result.symbols_scanned += 1
                except Exception as e:
                    error_msg = f"Error analyzing {symbol} {timeframe}: {e}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)

        # Categorize results
        result.valid_setups = self.trade_calculator.filter_valid_setups(result.all_setups)
        result.sniper_setups = self.trade_calculator.get_sniper_setups(result.all_setups)
        result.high_probability_setups = self.trade_calculator.get_high_probability_setups(
            result.all_setups
        )
        result.watchlist_setups = self.trade_calculator.get_watchlist_setups(result.all_setups)

        # Categorize zones
        result.fresh_zones = [
            z for z in result.all_zones
            if z.classification in (ZoneClassification.FRESH_CLEAN, ZoneClassification.FRESH)
        ]
        result.non_fresh_zones = [
            z for z in result.all_zones
            if z.classification == ZoneClassification.NON_FRESH
        ]

        result.scan_time = datetime.utcnow()
        self._last_scan_result = result

        logger.info(f"Scan complete: {len(result.valid_setups)} valid setups found")
        return result

    async def scan_symbol(self, symbol: str) -> ScanResult:
        """Scan a single symbol across all timeframes."""
        result = ScanResult()

        for timeframe in Config.TIMEFRAMES:
            df = await self.data_fetcher.fetch_ohlc(symbol, timeframe)
            if df is None or len(df) < 50:
                continue

            try:
                setups, zones = await self._analyze_symbol(
                    symbol, timeframe, df, {}
                )
                result.all_setups.extend(setups)
                result.all_zones.extend(zones)
                result.symbols_scanned += 1
            except Exception as e:
                error_msg = f"Error analyzing {symbol} {timeframe}: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        # Categorize
        self._categorize_results(result)

        result.scan_time = datetime.utcnow()
        return result

    def _categorize_results(self, result: ScanResult):
        """Categorize scan results into setup types and zone types."""
        result.valid_setups = self.trade_calculator.filter_valid_setups(result.all_setups)
        result.sniper_setups = self.trade_calculator.get_sniper_setups(result.all_setups)
        result.high_probability_setups = self.trade_calculator.get_high_probability_setups(
            result.all_setups
        )
        result.watchlist_setups = self.trade_calculator.get_watchlist_setups(result.all_setups)
        result.fresh_zones = [
            z for z in result.all_zones
            if z.classification in (ZoneClassification.FRESH_CLEAN, ZoneClassification.FRESH)
        ]
        result.non_fresh_zones = [
            z for z in result.all_zones
            if z.classification == ZoneClassification.NON_FRESH
        ]

    async def _analyze_symbol(
        self, symbol: str, timeframe: str,
        df: pd.DataFrame, all_data: Dict[str, Optional[pd.DataFrame]]
    ) -> Tuple[List[TradeSetup], List[SNRZone]]:
        """
        Full analysis pipeline for a single symbol/timeframe.
        """
        setups: List[TradeSetup] = []

        # Step 1: Detect SNR zones
        zones = self.snr_engine.detect_zones(symbol, timeframe, df)

        if not zones:
            return setups, []

        # Step 2: Get H4 data for trend alignment
        h4_df = None
        if timeframe != "H4":
            h4_df = await self.data_fetcher.fetch_ohlc(symbol, "H4")

        # Step 3: Run confluence analysis
        confluence = self.confluence_detector.analyze(
            symbol=symbol,
            timeframe=timeframe,
            df=df,
            h4_df=h4_df,
        )

        # Step 4: Check multi-timeframe alignment
        mtf_aligned = await self._check_mtf_alignment(symbol, timeframe, zones, all_data)

        # Step 5: Get current price
        current_price = self.data_fetcher.get_current_price(df)

        # Step 6: Calculate setups for each valid zone
        for zone in zones:
            # Skip zones that are far from current price
            if not self._is_zone_actionable(zone, current_price, df):
                continue

            setup = self.trade_calculator.calculate_setup(
                zone=zone,
                current_price=current_price,
                all_zones=zones,
                confluence=confluence,
                mtf_aligned=mtf_aligned,
            )

            setups.append(setup)

        return setups, zones

    async def _check_mtf_alignment(
        self, symbol: str, current_tf: str,
        zones: List[SNRZone], all_data: Dict[str, Optional[pd.DataFrame]]
    ) -> bool:
        """
        Check if multiple timeframes align.
        True if the same zone type exists on at least 2 timeframes.
        """
        if current_tf == "H4":
            # H4 is the highest, check if H1 aligns
            h1_df = await self.data_fetcher.fetch_ohlc(symbol, "H1")
            if h1_df is not None and len(h1_df) >= 50:
                h1_zones = self.snr_engine.detect_zones(symbol, "H1", h1_df)
                # Check if same zone types exist nearby
                for zone in zones:
                    for h1_zone in h1_zones:
                        if (zone.zone_type == h1_zone.zone_type and
                                self._zones_overlap(zone, h1_zone)):
                            return True
        elif current_tf == "H1":
            # Check H4 alignment
            h4_df = await self.data_fetcher.fetch_ohlc(symbol, "H4")
            if h4_df is not None and len(h4_df) >= 50:
                h4_zones = self.snr_engine.detect_zones(symbol, "H4", h4_df)
                for zone in zones:
                    for h4_zone in h4_zones:
                        if (zone.zone_type == h4_zone.zone_type and
                                self._zones_overlap(zone, h4_zone)):
                            return True
        elif current_tf == "M15":
            # Check H1 alignment
            h1_df = await self.data_fetcher.fetch_ohlc(symbol, "H1")
            if h1_df is not None and len(h1_df) >= 50:
                h1_zones = self.snr_engine.detect_zones(symbol, "H1", h1_df)
                for zone in zones:
                    for h1_zone in h1_zones:
                        if (zone.zone_type == h1_zone.zone_type and
                                self._zones_overlap(zone, h1_zone)):
                            return True

        return False

    def _zones_overlap(self, zone1: SNRZone, zone2: SNRZone) -> bool:
        """Check if two zones overlap or are very close."""
        # Zones overlap if one's range intersects the other
        return not (zone1.zone_top < zone2.zone_bottom or zone2.zone_top < zone1.zone_bottom)

    def _is_zone_actionable(
        self, zone: SNRZone, current_price: float, df: pd.DataFrame
    ) -> bool:
        """
        Check if zone is close enough to current price to be actionable.
        Zone should be within 5 ATR of current price.
        """
        atr = self.snr_engine.calculate_atr(df)
        if atr.empty or pd.isna(atr.iloc[-1]):
            return True  # Allow if we can't calculate ATR

        current_atr = atr.iloc[-1]
        max_distance = current_atr * 5

        if zone.zone_type == ZoneType.SUPPORT:
            distance = current_price - zone.zone_top
        else:
            distance = zone.zone_bottom - current_price

        return abs(distance) <= max_distance

    def get_last_result(self) -> Optional[ScanResult]:
        """Get the last scan result."""
        return self._last_scan_result

    async def close(self):
        """Cleanup resources."""
        await self.data_fetcher.close()
