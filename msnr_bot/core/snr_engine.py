"""
Core SNR (Support & Resistance) Detection Engine.

Implements the Malaysia SNR methodology:
- Swing High/Low detection
- Zone creation with configurable buffers
- Touch counting (Fresh/Non-Fresh/Expired)
- Departure strength measurement
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
from datetime import datetime

from msnr_bot.config import Config


class ZoneType(Enum):
    """Zone classification types."""
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class ZoneStatus(Enum):
    """Zone freshness status."""
    FRESH = "FRESH"
    NON_FRESH_FIRST_RETEST = "NON-FRESH FIRST RETEST"
    EXPIRED = "EXPIRED"


class DepartureStrength(Enum):
    """Departure strength classification."""
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"


class ZoneClassification(Enum):
    """Overall zone classification."""
    FRESH_CLEAN = "FRESH CLEAN"
    FRESH = "FRESH"
    NON_FRESH = "NON-FRESH"
    EXPIRED = "EXPIRED"


@dataclass
class SNRZone:
    """Represents a Support or Resistance zone."""
    symbol: str
    timeframe: str
    zone_type: ZoneType
    zone_top: float
    zone_bottom: float
    swing_price: float
    touch_count: int = 0
    status: ZoneStatus = ZoneStatus.FRESH
    departure_strength: DepartureStrength = DepartureStrength.WEAK
    departure_distance: float = 0.0
    classification: ZoneClassification = ZoneClassification.FRESH_CLEAN
    creation_time: datetime = field(default_factory=datetime.utcnow)
    last_update: datetime = field(default_factory=datetime.utcnow)
    candle_index: int = 0  # Index where zone was created

    def to_dict(self) -> dict:
        """Convert zone to dictionary for storage."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "zone_type": self.zone_type.value,
            "zone_top": self.zone_top,
            "zone_bottom": self.zone_bottom,
            "swing_price": self.swing_price,
            "touch_count": self.touch_count,
            "status": self.status.value,
            "departure_strength": self.departure_strength.value,
            "departure_distance": self.departure_distance,
            "classification": self.classification.value,
            "creation_time": self.creation_time.isoformat(),
            "last_update": self.last_update.isoformat(),
            "candle_index": self.candle_index,
        }


class SNREngine:
    """
    Core engine for detecting Support and Resistance zones
    using Malaysia SNR methodology.
    """

    def __init__(self):
        self.left_bars = Config.SWING_LEFT_BARS
        self.right_bars = Config.SWING_RIGHT_BARS
        self.buffer_multiplier = Config.ZONE_BUFFER_ATR_MULTIPLIER

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()

        return atr

    def detect_swing_highs(self, df: pd.DataFrame) -> List[int]:
        """
        Detect swing highs.
        A candle high is higher than at least 2 candles on left and 2 on right.
        """
        highs = df["high"].values
        swing_high_indices = []

        for i in range(self.left_bars, len(highs) - self.right_bars):
            is_swing_high = True

            # Check left candles
            for j in range(1, self.left_bars + 1):
                if highs[i] <= highs[i - j]:
                    is_swing_high = False
                    break

            if not is_swing_high:
                continue

            # Check right candles
            for j in range(1, self.right_bars + 1):
                if highs[i] <= highs[i + j]:
                    is_swing_high = False
                    break

            if is_swing_high:
                swing_high_indices.append(i)

        return swing_high_indices

    def detect_swing_lows(self, df: pd.DataFrame) -> List[int]:
        """
        Detect swing lows.
        A candle low is lower than at least 2 candles on left and 2 on right.
        """
        lows = df["low"].values
        swing_low_indices = []

        for i in range(self.left_bars, len(lows) - self.right_bars):
            is_swing_low = True

            # Check left candles
            for j in range(1, self.left_bars + 1):
                if lows[i] >= lows[i - j]:
                    is_swing_low = False
                    break

            if not is_swing_low:
                continue

            # Check right candles
            for j in range(1, self.right_bars + 1):
                if lows[i] >= lows[i + j]:
                    is_swing_low = False
                    break

            if is_swing_low:
                swing_low_indices.append(i)

        return swing_low_indices

    def create_resistance_zone(
        self, symbol: str, timeframe: str, swing_high: float,
        atr_value: float, candle_index: int
    ) -> SNRZone:
        """
        Create a Resistance Zone from a swing high.
        Zone Top = Swing High
        Zone Bottom = Swing High - configurable buffer (0.1 ATR default)
        """
        buffer = atr_value * self.buffer_multiplier
        zone = SNRZone(
            symbol=symbol,
            timeframe=timeframe,
            zone_type=ZoneType.RESISTANCE,
            zone_top=swing_high,
            zone_bottom=swing_high - buffer,
            swing_price=swing_high,
            candle_index=candle_index,
        )
        return zone

    def create_support_zone(
        self, symbol: str, timeframe: str, swing_low: float,
        atr_value: float, candle_index: int
    ) -> SNRZone:
        """
        Create a Support Zone from a swing low.
        Zone Top = Swing Low + configurable buffer (0.1 ATR default)
        Zone Bottom = Swing Low
        """
        buffer = atr_value * self.buffer_multiplier
        zone = SNRZone(
            symbol=symbol,
            timeframe=timeframe,
            zone_type=ZoneType.SUPPORT,
            zone_top=swing_low + buffer,
            zone_bottom=swing_low,
            swing_price=swing_low,
            candle_index=candle_index,
        )
        return zone

    def count_touches(self, zone: SNRZone, df: pd.DataFrame) -> int:
        """
        Count how many times price has touched the zone.
        A touch occurs when candle wick enters the zone.
        Only counts candles AFTER zone creation.
        """
        touch_count = 0
        start_idx = zone.candle_index + self.right_bars + 1

        for i in range(start_idx, len(df)):
            candle_high = df.iloc[i]["high"]
            candle_low = df.iloc[i]["low"]

            if zone.zone_type == ZoneType.RESISTANCE:
                # Touch if wick enters resistance zone from below
                if candle_high >= zone.zone_bottom and candle_low < zone.zone_top:
                    touch_count += 1
            else:
                # Touch if wick enters support zone from above
                if candle_low <= zone.zone_top and candle_high > zone.zone_bottom:
                    touch_count += 1

        return touch_count

    def classify_zone_status(self, touch_count: int) -> ZoneStatus:
        """
        Classify zone status based on touch count.
        0 touches = FRESH
        1 touch = NON-FRESH FIRST RETEST
        >1 touches = EXPIRED
        """
        if touch_count == 0:
            return ZoneStatus.FRESH
        elif touch_count == 1:
            return ZoneStatus.NON_FRESH_FIRST_RETEST
        else:
            return ZoneStatus.EXPIRED

    def measure_departure(self, zone: SNRZone, df: pd.DataFrame, atr: pd.Series) -> tuple:
        """
        Measure how aggressively price leaves the zone.
        Returns (DepartureStrength, distance_in_atr).
        """
        start_idx = zone.candle_index + 1
        if start_idx >= len(df):
            return DepartureStrength.WEAK, 0.0

        atr_at_zone = atr.iloc[zone.candle_index]
        if atr_at_zone == 0 or pd.isna(atr_at_zone):
            return DepartureStrength.WEAK, 0.0

        # Measure max distance from zone in the next candles (up to 10)
        max_distance = 0.0
        end_idx = min(start_idx + 10, len(df))

        for i in range(start_idx, end_idx):
            if zone.zone_type == ZoneType.RESISTANCE:
                # For resistance, departure is downward
                distance = zone.zone_bottom - df.iloc[i]["low"]
            else:
                # For support, departure is upward
                distance = df.iloc[i]["high"] - zone.zone_top

            if distance > max_distance:
                max_distance = distance

        distance_in_atr = max_distance / atr_at_zone

        if distance_in_atr >= Config.DEPARTURE_STRONG:
            strength = DepartureStrength.STRONG
        elif distance_in_atr >= Config.DEPARTURE_MEDIUM:
            strength = DepartureStrength.MEDIUM
        else:
            strength = DepartureStrength.WEAK

        return strength, distance_in_atr

    def classify_zone(self, zone: SNRZone) -> ZoneClassification:
        """
        Classify zone based on touch count and departure strength.
        Fresh + Strong Departure = FRESH CLEAN
        Fresh + Medium Departure = FRESH
        Any with Weak Departure = reduce score (still classify based on touch)
        Non-Fresh or Expired based on touches
        """
        if zone.touch_count == 0 and zone.departure_strength == DepartureStrength.STRONG:
            return ZoneClassification.FRESH_CLEAN
        elif zone.touch_count == 0 and zone.departure_strength == DepartureStrength.MEDIUM:
            return ZoneClassification.FRESH
        elif zone.touch_count == 0:
            return ZoneClassification.FRESH
        elif zone.touch_count == 1:
            return ZoneClassification.NON_FRESH
        else:
            return ZoneClassification.EXPIRED

    def detect_zones(self, symbol: str, timeframe: str, df: pd.DataFrame) -> List[SNRZone]:
        """
        Main detection method. Finds all SNR zones for given OHLC data.
        Returns list of valid (non-expired) zones, deduplicated.
        """
        if len(df) < 20:
            return []

        atr = self.calculate_atr(df)
        zones = []

        # Detect swing highs and create resistance zones
        swing_highs = self.detect_swing_highs(df)
        for idx in swing_highs:
            atr_value = atr.iloc[idx]
            if pd.isna(atr_value) or atr_value == 0:
                continue

            zone = self.create_resistance_zone(
                symbol=symbol,
                timeframe=timeframe,
                swing_high=df.iloc[idx]["high"],
                atr_value=atr_value,
                candle_index=idx,
            )

            # Count touches
            zone.touch_count = self.count_touches(zone, df)
            zone.status = self.classify_zone_status(zone.touch_count)

            # Skip expired zones
            if zone.status == ZoneStatus.EXPIRED:
                continue

            # Measure departure
            zone.departure_strength, zone.departure_distance = self.measure_departure(
                zone, df, atr
            )

            # Classify zone
            zone.classification = self.classify_zone(zone)

            zone.last_update = datetime.utcnow()
            zones.append(zone)

        # Detect swing lows and create support zones
        swing_lows = self.detect_swing_lows(df)
        for idx in swing_lows:
            atr_value = atr.iloc[idx]
            if pd.isna(atr_value) or atr_value == 0:
                continue

            zone = self.create_support_zone(
                symbol=symbol,
                timeframe=timeframe,
                swing_low=df.iloc[idx]["low"],
                atr_value=atr_value,
                candle_index=idx,
            )

            # Count touches
            zone.touch_count = self.count_touches(zone, df)
            zone.status = self.classify_zone_status(zone.touch_count)

            # Skip expired zones
            if zone.status == ZoneStatus.EXPIRED:
                continue

            # Measure departure
            zone.departure_strength, zone.departure_distance = self.measure_departure(
                zone, df, atr
            )

            # Classify zone
            zone.classification = self.classify_zone(zone)

            zone.last_update = datetime.utcnow()
            zones.append(zone)

        # DEDUPLICATE: Remove zones that are too close to each other
        zones = self._deduplicate_zones(zones, atr)

        return zones

    def _deduplicate_zones(self, zones: List[SNRZone], atr: pd.Series) -> List[SNRZone]:
        """
        Remove duplicate zones that overlap or are within 1 ATR of each other.
        Keeps the zone with the best departure strength and most recent creation.
        """
        if not zones or atr.empty:
            return zones

        current_atr = atr.iloc[-1]
        if pd.isna(current_atr) or current_atr == 0:
            return zones

        # Separate by type
        support_zones = [z for z in zones if z.zone_type == ZoneType.SUPPORT]
        resistance_zones = [z for z in zones if z.zone_type == ZoneType.RESISTANCE]

        deduped_support = self._dedup_group(support_zones, current_atr)
        deduped_resistance = self._dedup_group(resistance_zones, current_atr)

        return deduped_support + deduped_resistance

    def _dedup_group(self, zones: List[SNRZone], atr: float) -> List[SNRZone]:
        """Deduplicate a group of same-type zones."""
        if not zones:
            return []

        # Sort by swing price
        zones.sort(key=lambda z: z.swing_price)

        deduped = []
        i = 0
        while i < len(zones):
            # Collect all zones within 1 ATR of this one
            cluster = [zones[i]]
            j = i + 1
            while j < len(zones) and abs(zones[j].swing_price - zones[i].swing_price) < atr:
                cluster.append(zones[j])
                j += 1

            # Keep the BEST zone from the cluster
            # Priority: strongest departure > most recent
            best = max(cluster, key=lambda z: (
                z.departure_distance,  # Strongest departure
                z.candle_index,        # Most recent
            ))
            deduped.append(best)

            i = j

        return deduped

    def get_nearest_resistance(
        self, zones: List[SNRZone], current_price: float
    ) -> Optional[SNRZone]:
        """Get the nearest resistance zone above current price."""
        resistance_zones = [
            z for z in zones
            if z.zone_type == ZoneType.RESISTANCE and z.zone_bottom > current_price
        ]
        if not resistance_zones:
            return None
        return min(resistance_zones, key=lambda z: z.zone_bottom - current_price)

    def get_nearest_support(
        self, zones: List[SNRZone], current_price: float
    ) -> Optional[SNRZone]:
        """Get the nearest support zone below current price."""
        support_zones = [
            z for z in zones
            if z.zone_type == ZoneType.SUPPORT and z.zone_top < current_price
        ]
        if not support_zones:
            return None
        return min(support_zones, key=lambda z: current_price - z.zone_top)
