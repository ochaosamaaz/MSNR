"""
Trade Setup Calculator.

Calculates:
- Entry price
- Stop Loss (with buffer)
- Take Profit (nearest valid SNR level)
- Risk-Reward Ratio
- Validates setups against rules (max SL, min RRR)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from msnr_bot.config import Config
from msnr_bot.core.snr_engine import SNRZone, ZoneType
from msnr_bot.core.confluence import ConfluenceResult
from msnr_bot.core.scoring import ScoreBreakdown, ScoringEngine, SetupType, Grade


class TradeDirection(Enum):
    """Trade direction."""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class TradeSetup:
    """Complete trade setup with all calculated values."""
    symbol: str
    timeframe: str
    direction: TradeDirection
    entry: float
    stop_loss: float
    take_profit: float
    sl_distance_pips: float
    tp_distance_pips: float
    risk_reward_ratio: float
    zone: Optional[SNRZone] = None
    confluence: Optional[ConfluenceResult] = None
    score_breakdown: Optional[ScoreBreakdown] = None
    is_valid: bool = False
    rejection_reason: str = ""
    tp_target_description: str = ""
    creation_time: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction.value,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "sl_distance_pips": self.sl_distance_pips,
            "tp_distance_pips": self.tp_distance_pips,
            "risk_reward_ratio": self.risk_reward_ratio,
            "zone_type": self.zone.zone_type.value if self.zone else "",
            "zone_classification": self.zone.classification.value if self.zone else "",
            "touch_count": self.zone.touch_count if self.zone else 0,
            "departure_strength": self.zone.departure_strength.value if self.zone else "",
            "sweep": self._has_aligned_sweep(),
            "bos": self._has_aligned_bos(),
            "fvg": self._has_aligned_fvg(),
            "score": self.score_breakdown.total_score if self.score_breakdown else 0,
            "grade": self.score_breakdown.grade.value if self.score_breakdown else "",
            "setup_type": self.score_breakdown.setup_type.value if self.score_breakdown else "",
            "is_valid": self.is_valid,
            "rejection_reason": self.rejection_reason,
            "tp_target_description": self.tp_target_description,
            "creation_time": self.creation_time.isoformat(),
        }

    def _has_aligned_sweep(self) -> bool:
        """Check if sweep aligns with direction."""
        if not self.confluence:
            return False
        if self.direction == TradeDirection.BUY:
            return self.confluence.liquidity_sweep_bullish
        return self.confluence.liquidity_sweep_bearish

    def _has_aligned_bos(self) -> bool:
        """Check if BOS aligns with direction."""
        if not self.confluence:
            return False
        if self.direction == TradeDirection.BUY:
            return self.confluence.bos_bullish
        return self.confluence.bos_bearish

    def _has_aligned_fvg(self) -> bool:
        """Check if FVG aligns with direction."""
        if not self.confluence:
            return False
        if self.direction == TradeDirection.BUY:
            return self.confluence.fvg_bullish
        return self.confluence.fvg_bearish


class TradeCalculator:
    """
    Calculates complete trade setups from zones and market data.
    """

    def __init__(self):
        self.sl_buffer_pips = Config.SL_BUFFER_PIPS
        self.max_sl_pips = Config.MAX_SL_PIPS
        self.min_rrr = Config.MIN_RRR
        self.scoring_engine = ScoringEngine()

    def calculate_setup(
        self,
        zone: SNRZone,
        current_price: float,
        all_zones: List[SNRZone],
        confluence: ConfluenceResult,
        mtf_aligned: bool = False,
    ) -> TradeSetup:
        """
        Calculate a complete trade setup from a zone.

        For BUY (support zone):
            Entry = current price (at zone)
            SL = Below support zone - buffer
            TP = Nearest resistance zone above entry

        For SELL (resistance zone):
            Entry = current price (at zone)
            SL = Above resistance zone + buffer
            TP = Nearest support zone below entry
        """
        pip_value = Config.get_pip_value(zone.symbol)

        # Determine direction
        if zone.zone_type == ZoneType.SUPPORT:
            direction = TradeDirection.BUY
        else:
            direction = TradeDirection.SELL

        # Calculate entry (zone edge closest to current price)
        entry = self._calculate_entry(zone, current_price)

        # Calculate stop loss
        stop_loss = self._calculate_stop_loss(zone, pip_value)

        # Calculate SL distance in pips
        sl_distance = abs(entry - stop_loss) / pip_value

        # Calculate take profit
        take_profit, tp_description = self._calculate_take_profit(
            zone, entry, all_zones, current_price
        )

        # Calculate TP distance in pips
        tp_distance = abs(take_profit - entry) / pip_value if take_profit else 0

        # Calculate Risk-Reward Ratio
        rrr = tp_distance / sl_distance if sl_distance > 0 else 0

        # Create setup
        setup = TradeSetup(
            symbol=zone.symbol,
            timeframe=zone.timeframe,
            direction=direction,
            entry=round(entry, self._get_decimals(zone.symbol)),
            stop_loss=round(stop_loss, self._get_decimals(zone.symbol)),
            take_profit=round(take_profit, self._get_decimals(zone.symbol)),
            sl_distance_pips=round(sl_distance, 1),
            tp_distance_pips=round(tp_distance, 1),
            risk_reward_ratio=round(rrr, 2),
            zone=zone,
            confluence=confluence,
            tp_target_description=tp_description,
        )

        # Calculate score
        setup.score_breakdown = self.scoring_engine.calculate_score(
            zone=zone,
            confluence=confluence,
            rrr=rrr,
            sl_pips=sl_distance,
            mtf_aligned=mtf_aligned,
        )

        # Validate setup
        setup.is_valid, setup.rejection_reason = self._validate_setup(setup)

        return setup

    def _calculate_entry(self, zone: SNRZone, current_price: float) -> float:
        """Calculate entry price at zone edge."""
        if zone.zone_type == ZoneType.SUPPORT:
            # BUY at the top of support zone
            return zone.zone_top
        else:
            # SELL at the bottom of resistance zone
            return zone.zone_bottom

    def _calculate_stop_loss(self, zone: SNRZone, pip_value: float) -> float:
        """
        Calculate stop loss with buffer.

        BUY: SL = Below support zone bottom - 5-10 pip buffer
        SELL: SL = Above resistance zone top + 5-10 pip buffer
        """
        buffer = self.sl_buffer_pips * pip_value

        if zone.zone_type == ZoneType.SUPPORT:
            # SL below support zone
            return zone.zone_bottom - buffer
        else:
            # SL above resistance zone
            return zone.zone_top + buffer

    def _calculate_take_profit(
        self, zone: SNRZone, entry: float,
        all_zones: List[SNRZone], current_price: float
    ) -> tuple:
        """
        Calculate take profit targeting nearest valid SNR level.

        BUY: TP = Nearest Resistance Zone above entry
        SELL: TP = Nearest Support Zone below entry
        """
        if zone.zone_type == ZoneType.SUPPORT:
            # BUY: Target nearest resistance above
            resistance_zones = [
                z for z in all_zones
                if z.zone_type == ZoneType.RESISTANCE
                and z.zone_bottom > entry
                and z.symbol == zone.symbol
                and z.timeframe == zone.timeframe
            ]
            if resistance_zones:
                nearest = min(resistance_zones, key=lambda z: z.zone_bottom - entry)
                return nearest.zone_bottom, "Nearest Resistance"
            else:
                # Fallback: use 2x SL distance
                pip_value = Config.get_pip_value(zone.symbol)
                sl_dist = entry - (zone.zone_bottom - self.sl_buffer_pips * pip_value)
                return entry + (sl_dist * 2), "2x SL Distance"
        else:
            # SELL: Target nearest support below
            support_zones = [
                z for z in all_zones
                if z.zone_type == ZoneType.SUPPORT
                and z.zone_top < entry
                and z.symbol == zone.symbol
                and z.timeframe == zone.timeframe
            ]
            if support_zones:
                nearest = min(support_zones, key=lambda z: entry - z.zone_top)
                return nearest.zone_top, "Nearest Support"
            else:
                # Fallback: use 2x SL distance
                pip_value = Config.get_pip_value(zone.symbol)
                sl_dist = (zone.zone_top + self.sl_buffer_pips * pip_value) - entry
                return entry - (sl_dist * 2), "2x SL Distance"

    def _validate_setup(self, setup: TradeSetup) -> tuple:
        """
        Validate setup against rules.

        Rejection criteria:
        - SL > 50 pips (Forex)
        - RRR < 1.5
        - Score below 70
        - Zone expired

        Returns: (is_valid, rejection_reason)
        """
        symbol_category = Config.get_symbol_category(setup.symbol)

        # Check SL limit (applies to Forex and Metals)
        if symbol_category in ("FOREX_MAJOR", "FOREX_MINOR", "METALS"):
            if setup.sl_distance_pips > self.max_sl_pips:
                return False, f"SL too large: {setup.sl_distance_pips} pips > {self.max_sl_pips} max"

        # Check RRR
        if setup.risk_reward_ratio < self.min_rrr:
            return False, f"RRR too low: {setup.risk_reward_ratio} < {self.min_rrr} min"

        # Check score
        if setup.score_breakdown and setup.score_breakdown.total_score < Config.MIN_SCORE_ALERT:
            return False, f"Score too low: {setup.score_breakdown.total_score} < {Config.MIN_SCORE_ALERT}"

        # Check setup type
        if setup.score_breakdown and setup.score_breakdown.setup_type == SetupType.INVALID:
            return False, "Setup does not meet minimum classification criteria"

        return True, ""

    def _get_decimals(self, symbol: str) -> int:
        """Get decimal places for price formatting."""
        if symbol in Config.CRYPTO:
            if symbol in ("BTCUSDT", "ETHUSDT"):
                return 2
            return 4
        elif "JPY" in symbol:
            return 3
        elif symbol == "XAUUSD":
            return 2
        else:
            return 5

    def filter_valid_setups(self, setups: List[TradeSetup]) -> List[TradeSetup]:
        """Filter and sort setups by validity and priority."""
        valid = [s for s in setups if s.is_valid]
        # Sort by score descending
        valid.sort(
            key=lambda s: s.score_breakdown.total_score if s.score_breakdown else 0,
            reverse=True,
        )
        return valid

    def get_sniper_setups(self, setups: List[TradeSetup]) -> List[TradeSetup]:
        """Get only SNIPER setups."""
        return [
            s for s in setups
            if s.is_valid and s.score_breakdown
            and s.score_breakdown.setup_type == SetupType.SNIPER
        ]

    def get_high_probability_setups(self, setups: List[TradeSetup]) -> List[TradeSetup]:
        """Get HIGH PROBABILITY and SNIPER setups."""
        return [
            s for s in setups
            if s.is_valid and s.score_breakdown
            and s.score_breakdown.setup_type in (
                SetupType.SNIPER, SetupType.HIGH_PROBABILITY
            )
        ]

    def get_watchlist_setups(self, setups: List[TradeSetup]) -> List[TradeSetup]:
        """Get Grade A and A+ setups."""
        return [
            s for s in setups
            if s.is_valid and s.score_breakdown
            and s.score_breakdown.grade in (Grade.A_PLUS, Grade.A)
        ]
