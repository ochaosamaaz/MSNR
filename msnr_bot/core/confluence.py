"""
Confluence Detection Module.

Detects additional confirmation signals:
- Liquidity Sweep (price sweeps swing high/low then reverses)
- Break of Structure (BOS)
- Fair Value Gap (FVG / imbalance)
- H4 Trend Alignment
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum


class TrendDirection(Enum):
    """Market trend direction."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class ConfluenceResult:
    """Results of confluence analysis for a symbol/timeframe."""
    symbol: str
    timeframe: str
    liquidity_sweep_bullish: bool = False
    liquidity_sweep_bearish: bool = False
    bos_bullish: bool = False
    bos_bearish: bool = False
    fvg_bullish: bool = False
    fvg_bearish: bool = False
    h4_trend: TrendDirection = TrendDirection.NEUTRAL
    h4_aligned_support: bool = False
    h4_aligned_resistance: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "liquidity_sweep_bullish": self.liquidity_sweep_bullish,
            "liquidity_sweep_bearish": self.liquidity_sweep_bearish,
            "bos_bullish": self.bos_bullish,
            "bos_bearish": self.bos_bearish,
            "fvg_bullish": self.fvg_bullish,
            "fvg_bearish": self.fvg_bearish,
            "h4_trend": self.h4_trend.value,
            "h4_aligned_support": self.h4_aligned_support,
            "h4_aligned_resistance": self.h4_aligned_resistance,
        }


class ConfluenceDetector:
    """
    Detects confluence factors for trade setups.
    """

    def __init__(self, swing_left: int = 2, swing_right: int = 2):
        self.swing_left = swing_left
        self.swing_right = swing_right

    # ─────────────────────────────────────────────
    # LIQUIDITY SWEEP DETECTION
    # ─────────────────────────────────────────────

    def detect_liquidity_sweep(
        self, df: pd.DataFrame, lookback: int = 20
    ) -> Tuple[bool, bool]:
        """
        Detect liquidity sweeps in recent price action.

        Bearish Sweep: Price sweeps previous swing high and closes back below.
        Bullish Sweep: Price sweeps previous swing low and closes back above.

        Returns: (bullish_sweep, bearish_sweep)
        """
        if len(df) < lookback + 5:
            return False, False

        bullish_sweep = False
        bearish_sweep = False

        # Find recent swing highs and lows in the lookback period
        recent_df = df.iloc[-(lookback + 5):]
        swing_highs = self._find_swing_highs(recent_df)
        swing_lows = self._find_swing_lows(recent_df)

        # Check last few candles for sweep
        check_range = min(5, len(df) - 1)

        for i in range(1, check_range + 1):
            current = df.iloc[-i]

            # Bearish sweep: wick above swing high, close below
            for sh_idx in swing_highs:
                sh_price = recent_df.iloc[sh_idx]["high"]
                if (current["high"] > sh_price and
                        current["close"] < sh_price):
                    bearish_sweep = True
                    break

            # Bullish sweep: wick below swing low, close above
            for sl_idx in swing_lows:
                sl_price = recent_df.iloc[sl_idx]["low"]
                if (current["low"] < sl_price and
                        current["close"] > sl_price):
                    bullish_sweep = True
                    break

        return bullish_sweep, bearish_sweep

    # ─────────────────────────────────────────────
    # BREAK OF STRUCTURE (BOS) DETECTION
    # ─────────────────────────────────────────────

    def detect_bos(self, df: pd.DataFrame, lookback: int = 20) -> Tuple[bool, bool]:
        """
        Detect Break of Structure.

        Bullish BOS: Price breaks above a recent swing high (higher high).
        Bearish BOS: Price breaks below a recent swing low (lower low).

        Returns: (bullish_bos, bearish_bos)
        """
        if len(df) < lookback + 5:
            return False, False

        bullish_bos = False
        bearish_bos = False

        # Get swing points in lookback window (excluding last 3 candles)
        analysis_df = df.iloc[-(lookback + 5):-3]
        swing_highs = self._find_swing_highs(analysis_df)
        swing_lows = self._find_swing_lows(analysis_df)

        # Check if recent candles break structure
        last_candles = df.iloc[-3:]

        # Bullish BOS: recent close above previous swing high
        if swing_highs:
            highest_swing = max(analysis_df.iloc[idx]["high"] for idx in swing_highs)
            for _, candle in last_candles.iterrows():
                if candle["close"] > highest_swing:
                    bullish_bos = True
                    break

        # Bearish BOS: recent close below previous swing low
        if swing_lows:
            lowest_swing = min(analysis_df.iloc[idx]["low"] for idx in swing_lows)
            for _, candle in last_candles.iterrows():
                if candle["close"] < lowest_swing:
                    bearish_bos = True
                    break

        return bullish_bos, bearish_bos

    # ─────────────────────────────────────────────
    # FAIR VALUE GAP (FVG) DETECTION
    # ─────────────────────────────────────────────

    def detect_fvg(self, df: pd.DataFrame, lookback: int = 10) -> Tuple[bool, bool]:
        """
        Detect Fair Value Gaps (imbalances) in recent price action.

        Bullish FVG: Gap between candle 1 high and candle 3 low (3-candle pattern).
        Bearish FVG: Gap between candle 1 low and candle 3 high.

        Returns: (bullish_fvg, bearish_fvg)
        """
        if len(df) < lookback + 3:
            return False, False

        bullish_fvg = False
        bearish_fvg = False

        # Check last N candles for FVG patterns
        start_idx = max(0, len(df) - lookback)

        for i in range(start_idx, len(df) - 2):
            candle1 = df.iloc[i]
            candle2 = df.iloc[i + 1]
            candle3 = df.iloc[i + 2]

            # Bullish FVG: candle 3 low > candle 1 high (gap up)
            if candle3["low"] > candle1["high"]:
                bullish_fvg = True

            # Bearish FVG: candle 3 high < candle 1 low (gap down)
            if candle3["high"] < candle1["low"]:
                bearish_fvg = True

        return bullish_fvg, bearish_fvg

    # ─────────────────────────────────────────────
    # H4 TREND DETECTION
    # ─────────────────────────────────────────────

    def detect_h4_trend(self, h4_df: pd.DataFrame) -> TrendDirection:
        """
        Determine H4 trend direction using multiple methods:
        1. EMA 50 vs EMA 200 crossover
        2. Higher highs / lower lows structure
        3. Price position relative to EMAs
        """
        if len(h4_df) < 200:
            return self._simple_trend(h4_df)

        close = h4_df["close"]

        # Calculate EMAs
        ema_50 = close.ewm(span=50, adjust=False).mean()
        ema_200 = close.ewm(span=200, adjust=False).mean()

        current_price = close.iloc[-1]
        current_ema50 = ema_50.iloc[-1]
        current_ema200 = ema_200.iloc[-1]

        bullish_signals = 0
        bearish_signals = 0

        # Signal 1: EMA crossover
        if current_ema50 > current_ema200:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # Signal 2: Price above/below EMAs
        if current_price > current_ema50 and current_price > current_ema200:
            bullish_signals += 1
        elif current_price < current_ema50 and current_price < current_ema200:
            bearish_signals += 1

        # Signal 3: Higher highs / lower lows (last 20 candles)
        recent = h4_df.iloc[-20:]
        swing_highs = self._find_swing_highs(recent)
        swing_lows = self._find_swing_lows(recent)

        if len(swing_highs) >= 2:
            last_two_highs = [recent.iloc[idx]["high"] for idx in swing_highs[-2:]]
            if last_two_highs[-1] > last_two_highs[-2]:
                bullish_signals += 1
            else:
                bearish_signals += 1

        if len(swing_lows) >= 2:
            last_two_lows = [recent.iloc[idx]["low"] for idx in swing_lows[-2:]]
            if last_two_lows[-1] > last_two_lows[-2]:
                bullish_signals += 1
            else:
                bearish_signals += 1

        # Determine trend
        if bullish_signals >= 3:
            return TrendDirection.BULLISH
        elif bearish_signals >= 3:
            return TrendDirection.BEARISH
        else:
            return TrendDirection.NEUTRAL

    def _simple_trend(self, df: pd.DataFrame) -> TrendDirection:
        """Simple trend detection for limited data."""
        if len(df) < 20:
            return TrendDirection.NEUTRAL

        close = df["close"]
        ema_20 = close.ewm(span=20, adjust=False).mean()

        current_price = close.iloc[-1]
        ema_value = ema_20.iloc[-1]

        # Also check slope
        ema_slope = ema_20.iloc[-1] - ema_20.iloc[-5]

        if current_price > ema_value and ema_slope > 0:
            return TrendDirection.BULLISH
        elif current_price < ema_value and ema_slope < 0:
            return TrendDirection.BEARISH
        else:
            return TrendDirection.NEUTRAL

    # ─────────────────────────────────────────────
    # FULL CONFLUENCE ANALYSIS
    # ─────────────────────────────────────────────

    def analyze(
        self, symbol: str, timeframe: str,
        df: pd.DataFrame, h4_df: Optional[pd.DataFrame] = None
    ) -> ConfluenceResult:
        """
        Run full confluence analysis on a symbol/timeframe.
        """
        result = ConfluenceResult(symbol=symbol, timeframe=timeframe)

        # Liquidity Sweep
        bullish_sweep, bearish_sweep = self.detect_liquidity_sweep(df)
        result.liquidity_sweep_bullish = bullish_sweep
        result.liquidity_sweep_bearish = bearish_sweep

        # Break of Structure
        bullish_bos, bearish_bos = self.detect_bos(df)
        result.bos_bullish = bullish_bos
        result.bos_bearish = bearish_bos

        # Fair Value Gap
        bullish_fvg, bearish_fvg = self.detect_fvg(df)
        result.fvg_bullish = bullish_fvg
        result.fvg_bearish = bearish_fvg

        # H4 Trend
        if h4_df is not None and len(h4_df) > 20:
            result.h4_trend = self.detect_h4_trend(h4_df)
        elif timeframe == "H4":
            result.h4_trend = self.detect_h4_trend(df)

        # H4 Alignment
        if result.h4_trend == TrendDirection.BULLISH:
            result.h4_aligned_support = True
        elif result.h4_trend == TrendDirection.BEARISH:
            result.h4_aligned_resistance = True

        return result

    # ─────────────────────────────────────────────
    # HELPER METHODS
    # ─────────────────────────────────────────────

    def _find_swing_highs(self, df: pd.DataFrame) -> List[int]:
        """Find swing high indices in dataframe."""
        highs = df["high"].values
        indices = []

        for i in range(self.swing_left, len(highs) - self.swing_right):
            is_swing = True
            for j in range(1, self.swing_left + 1):
                if highs[i] <= highs[i - j]:
                    is_swing = False
                    break
            if not is_swing:
                continue
            for j in range(1, self.swing_right + 1):
                if highs[i] <= highs[i + j]:
                    is_swing = False
                    break
            if is_swing:
                indices.append(i)

        return indices

    def _find_swing_lows(self, df: pd.DataFrame) -> List[int]:
        """Find swing low indices in dataframe."""
        lows = df["low"].values
        indices = []

        for i in range(self.swing_left, len(lows) - self.swing_right):
            is_swing = True
            for j in range(1, self.swing_left + 1):
                if lows[i] >= lows[i - j]:
                    is_swing = False
                    break
            if not is_swing:
                continue
            for j in range(1, self.swing_right + 1):
                if lows[i] >= lows[i + j]:
                    is_swing = False
                    break
            if is_swing:
                indices.append(i)

        return indices
