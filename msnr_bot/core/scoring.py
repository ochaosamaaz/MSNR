"""
Scoring and Grading System for MSNR Trading Agent.

Scoring Breakdown:
- Fresh Zone = +40
- Touch Count = 0 = +20
- Strong Departure = +30
- H4 Alignment = +10
- Liquidity Sweep = +10
- BOS = +10
- FVG = +10
- Maximum Score = 100

Grading:
- 90-100 = Grade A+
- 70-89 = Grade A
- 50-69 = Grade B
- Below 50 = Ignore

Setup Classification:
- VALID: Fresh Clean + Score >= 70 + RRR >= 1.5 + SL <= 50 pips
- HIGH PROBABILITY: Fresh Clean + Sweep + BOS + FVG + Score >= 90
- SNIPER: Fresh Clean + Sweep + BOS + FVG + MTF Alignment + Score >= 95
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from msnr_bot.config import Config
from msnr_bot.core.snr_engine import (
    SNRZone, ZoneClassification, DepartureStrength, ZoneType
)
from msnr_bot.core.confluence import ConfluenceResult, TrendDirection


class Grade(Enum):
    """Setup grade classification."""
    A_PLUS = "A+"
    A = "A"
    B = "B"
    IGNORE = "IGNORE"


class SetupType(Enum):
    """Trade setup classification."""
    SNIPER = "SNIPER SETUP"
    HIGH_PROBABILITY = "HIGH PROBABILITY"
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass
class ScoreBreakdown:
    """Detailed score breakdown for transparency."""
    fresh_zone_score: int = 0
    touch_count_score: int = 0
    departure_score: int = 0
    h4_alignment_score: int = 0
    liquidity_sweep_score: int = 0
    bos_score: int = 0
    fvg_score: int = 0
    total_score: int = 0
    grade: Grade = Grade.IGNORE
    setup_type: SetupType = SetupType.INVALID

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "fresh_zone_score": self.fresh_zone_score,
            "touch_count_score": self.touch_count_score,
            "departure_score": self.departure_score,
            "h4_alignment_score": self.h4_alignment_score,
            "liquidity_sweep_score": self.liquidity_sweep_score,
            "bos_score": self.bos_score,
            "fvg_score": self.fvg_score,
            "total_score": self.total_score,
            "grade": self.grade.value,
            "setup_type": self.setup_type.value,
        }


class ScoringEngine:
    """
    Scores trade setups based on zone quality and confluence factors.
    """

    def __init__(self):
        self.max_score = Config.MAX_SCORE

    def calculate_score(
        self,
        zone: SNRZone,
        confluence: ConfluenceResult,
        rrr: float = 0.0,
        sl_pips: float = 0.0,
        mtf_aligned: bool = False,
    ) -> ScoreBreakdown:
        """
        Calculate the quality score for a trade setup.

        Args:
            zone: The SNR zone being evaluated
            confluence: Confluence analysis results
            rrr: Risk-reward ratio (for setup classification)
            sl_pips: Stop loss in pips (for setup classification)
            mtf_aligned: Whether multiple timeframes align

        Returns:
            ScoreBreakdown with detailed scoring
        """
        breakdown = ScoreBreakdown()

        # ─── FRESH ZONE SCORE (+40) ───
        if zone.classification in (
            ZoneClassification.FRESH_CLEAN, ZoneClassification.FRESH
        ):
            breakdown.fresh_zone_score = Config.SCORE_FRESH_ZONE

        # ─── TOUCH COUNT SCORE (+20) ───
        if zone.touch_count == 0:
            breakdown.touch_count_score = Config.SCORE_TOUCH_ZERO

        # ─── DEPARTURE STRENGTH SCORE (+30) ───
        if zone.departure_strength == DepartureStrength.STRONG:
            breakdown.departure_score = Config.SCORE_STRONG_DEPARTURE
        elif zone.departure_strength == DepartureStrength.MEDIUM:
            breakdown.departure_score = int(Config.SCORE_STRONG_DEPARTURE * 0.6)  # 18
        # Weak departure = 0 (score reduction by not adding)

        # ─── H4 ALIGNMENT SCORE (+10) ───
        if self._is_h4_aligned(zone, confluence):
            breakdown.h4_alignment_score = Config.SCORE_H4_ALIGNMENT

        # ─── LIQUIDITY SWEEP SCORE (+10) ───
        if self._has_sweep(zone, confluence):
            breakdown.liquidity_sweep_score = Config.SCORE_LIQUIDITY_SWEEP

        # ─── BOS SCORE (+10) ───
        if self._has_bos(zone, confluence):
            breakdown.bos_score = Config.SCORE_BOS

        # ─── FVG SCORE (+10) ───
        if self._has_fvg(zone, confluence):
            breakdown.fvg_score = Config.SCORE_FVG

        # ─── CALCULATE TOTAL ───
        breakdown.total_score = min(
            self.max_score,
            breakdown.fresh_zone_score
            + breakdown.touch_count_score
            + breakdown.departure_score
            + breakdown.h4_alignment_score
            + breakdown.liquidity_sweep_score
            + breakdown.bos_score
            + breakdown.fvg_score
        )

        # ─── ASSIGN GRADE ───
        breakdown.grade = self._assign_grade(breakdown.total_score)

        # ─── CLASSIFY SETUP TYPE ───
        breakdown.setup_type = self._classify_setup(
            zone=zone,
            confluence=confluence,
            score=breakdown.total_score,
            rrr=rrr,
            sl_pips=sl_pips,
            mtf_aligned=mtf_aligned,
        )

        return breakdown

    def _is_h4_aligned(self, zone: SNRZone, confluence: ConfluenceResult) -> bool:
        """Check if zone aligns with H4 trend."""
        if zone.zone_type == ZoneType.SUPPORT:
            # Support zones prioritized in bullish H4 trend
            return confluence.h4_aligned_support
        else:
            # Resistance zones prioritized in bearish H4 trend
            return confluence.h4_aligned_resistance

    def _has_sweep(self, zone: SNRZone, confluence: ConfluenceResult) -> bool:
        """Check if liquidity sweep aligns with zone type."""
        if zone.zone_type == ZoneType.SUPPORT:
            # Bullish sweep near support = confirmation
            return confluence.liquidity_sweep_bullish
        else:
            # Bearish sweep near resistance = confirmation
            return confluence.liquidity_sweep_bearish

    def _has_bos(self, zone: SNRZone, confluence: ConfluenceResult) -> bool:
        """Check if BOS aligns with zone type."""
        if zone.zone_type == ZoneType.SUPPORT:
            return confluence.bos_bullish
        else:
            return confluence.bos_bearish

    def _has_fvg(self, zone: SNRZone, confluence: ConfluenceResult) -> bool:
        """Check if FVG aligns with zone type."""
        if zone.zone_type == ZoneType.SUPPORT:
            return confluence.fvg_bullish
        else:
            return confluence.fvg_bearish

    def _assign_grade(self, score: int) -> Grade:
        """Assign grade based on score."""
        if score >= Config.GRADE_A_PLUS_MIN:
            return Grade.A_PLUS
        elif score >= Config.GRADE_A_MIN:
            return Grade.A
        elif score >= Config.GRADE_B_MIN:
            return Grade.B
        else:
            return Grade.IGNORE

    def _classify_setup(
        self,
        zone: SNRZone,
        confluence: ConfluenceResult,
        score: int,
        rrr: float,
        sl_pips: float,
        mtf_aligned: bool,
    ) -> SetupType:
        """
        Classify the setup type based on criteria.

        SNIPER: Fresh Clean + Sweep + BOS + FVG + MTF + Score >= 95
        HIGH PROBABILITY: Fresh Clean + Sweep + BOS + FVG + Score >= 90
        VALID: Fresh Clean + Score >= 70 + RRR >= 1.5 + SL <= 50 pips
        """
        is_fresh_clean = zone.classification == ZoneClassification.FRESH_CLEAN
        has_sweep = self._has_sweep(zone, confluence)
        has_bos = self._has_bos(zone, confluence)
        has_fvg = self._has_fvg(zone, confluence)

        # SNIPER: Highest quality
        if (is_fresh_clean and has_sweep and has_bos and has_fvg
                and mtf_aligned and score >= 95):
            return SetupType.SNIPER

        # HIGH PROBABILITY
        if (is_fresh_clean and has_sweep and has_bos and has_fvg
                and score >= 90):
            return SetupType.HIGH_PROBABILITY

        # VALID: Meets minimum criteria
        if (is_fresh_clean and score >= 70
                and rrr >= Config.MIN_RRR
                and (sl_pips <= Config.MAX_SL_PIPS or sl_pips == 0)):
            return SetupType.VALID

        return SetupType.INVALID

    def should_alert(self, breakdown: ScoreBreakdown) -> bool:
        """Determine if this setup warrants a Telegram alert."""
        if breakdown.setup_type == SetupType.INVALID:
            return False
        if breakdown.total_score < Config.MIN_SCORE_ALERT:
            return False
        if breakdown.grade == Grade.IGNORE:
            return False
        return True

    def get_priority(self, breakdown: ScoreBreakdown) -> int:
        """
        Get alert priority (higher = more important).
        Used for sorting and prioritizing alerts.
        """
        priority_map = {
            SetupType.SNIPER: 100,
            SetupType.HIGH_PROBABILITY: 80,
            SetupType.VALID: 60,
            SetupType.INVALID: 0,
        }
        base = priority_map.get(breakdown.setup_type, 0)
        return base + breakdown.total_score
