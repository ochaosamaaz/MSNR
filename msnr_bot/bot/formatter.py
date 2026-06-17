"""
Message Formatter for Telegram alerts and responses.

Formats trade setups, zone information, and scan results
into clean Telegram messages.
"""

from typing import List

from msnr_bot.core.snr_engine import SNRZone, ZoneType, ZoneClassification, DepartureStrength
from msnr_bot.core.scoring import Grade, SetupType
from msnr_bot.core.trade_setup import TradeSetup, TradeDirection
from msnr_bot.modules.scanner import ScanResult


class MessageFormatter:
    """Formats data into Telegram-friendly messages."""

    @staticmethod
    def format_setup_alert(setup: TradeSetup) -> str:
        """
        Format a trade setup as a Telegram alert message.
        Matches the exact format specified in requirements.
        """
        if not setup.score_breakdown:
            return ""

        # Determine emoji based on setup type
        if setup.score_breakdown.setup_type == SetupType.SNIPER:
            header = "🚨 MSNR SNIPER SETUP"
        elif setup.score_breakdown.setup_type == SetupType.HIGH_PROBABILITY:
            header = "⚡ MSNR HIGH PROBABILITY SETUP"
        else:
            header = "✅ MSNR VALID SETUP"

        # Direction emoji
        dir_emoji = "🟢" if setup.direction == TradeDirection.BUY else "🔴"

        # Sweep/BOS/FVG status
        sweep = "YES" if setup._has_aligned_sweep() else "NO"
        bos = "YES" if setup._has_aligned_bos() else "NO"
        fvg = "YES" if setup._has_aligned_fvg() else "NO"

        msg = (
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"PAIR:\n{setup.symbol}\n\n"
            f"TIMEFRAME:\n{setup.timeframe}\n\n"
            f"TYPE:\n{dir_emoji} {setup.direction.value}\n\n"
            f"ENTRY:\n{setup.entry}\n\n"
            f"STOP LOSS:\n{setup.stop_loss}\n\n"
            f"SL DISTANCE:\n{setup.sl_distance_pips} Pips\n\n"
            f"TAKE PROFIT:\n{setup.take_profit}\n\n"
            f"TP TARGET:\n{setup.tp_target_description}\n\n"
            f"RISK REWARD:\n1:{setup.risk_reward_ratio}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"ZONE:\n{setup.zone.classification.value if setup.zone else 'N/A'} "
            f"{setup.zone.zone_type.value if setup.zone else ''}\n\n"
            f"TOUCH COUNT:\n{setup.zone.touch_count if setup.zone else 0}\n\n"
            f"DEPARTURE:\n{setup.zone.departure_strength.value if setup.zone else 'N/A'}\n\n"
            f"SWEEP:\n{sweep}\n\n"
            f"BOS:\n{bos}\n\n"
            f"FVG:\n{fvg}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"SCORE:\n{setup.score_breakdown.total_score}\n\n"
            f"GRADE:\n{setup.score_breakdown.grade.value}\n\n"
            f"STATUS:\n{setup.score_breakdown.setup_type.value}\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )

        return msg

    @staticmethod
    def format_zone_info(zone: SNRZone) -> str:
        """Format a single zone's information."""
        zone_emoji = "🟢" if zone.zone_type == ZoneType.SUPPORT else "🔴"
        fresh_emoji = "✨" if zone.classification == ZoneClassification.FRESH_CLEAN else "📍"

        return (
            f"{zone_emoji} {fresh_emoji} {zone.symbol} | {zone.timeframe}\n"
            f"   Type: {zone.zone_type.value} ({zone.classification.value})\n"
            f"   Range: {zone.zone_bottom:.5f} - {zone.zone_top:.5f}\n"
            f"   Touches: {zone.touch_count} | Departure: {zone.departure_strength.value}\n"
        )

    @staticmethod
    def format_fresh_zones(zones: List[SNRZone]) -> str:
        """Format list of fresh zones."""
        if not zones:
            return "📭 No Fresh Clean zones detected."

        msg = "✨ FRESH CLEAN ZONES\n━━━━━━━━━━━━━━━━━━━━━\n\n"

        # Group by symbol
        symbols = {}
        for zone in zones:
            key = zone.symbol
            if key not in symbols:
                symbols[key] = []
            symbols[key].append(zone)

        for symbol, sym_zones in symbols.items():
            msg += f"📊 {symbol}\n"
            for zone in sym_zones:
                msg += MessageFormatter.format_zone_info(zone)
            msg += "\n"

        return msg

    @staticmethod
    def format_non_fresh_zones(zones: List[SNRZone]) -> str:
        """Format list of non-fresh zones."""
        if not zones:
            return "📭 No Non-Fresh zones detected."

        msg = "🟡 NON-FRESH ZONES (First Retest)\n━━━━━━━━━━━━━━━━━━━━━\n\n"

        symbols = {}
        for zone in zones:
            key = zone.symbol
            if key not in symbols:
                symbols[key] = []
            symbols[key].append(zone)

        for symbol, sym_zones in symbols.items():
            msg += f"📊 {symbol}\n"
            for zone in sym_zones:
                msg += MessageFormatter.format_zone_info(zone)
            msg += "\n"

        return msg

    @staticmethod
    def format_scan_summary(result: ScanResult) -> str:
        """Format scan summary."""
        return result.summary()

    @staticmethod
    def format_setups_list(setups: List[TradeSetup], title: str) -> str:
        """Format a list of setups as a compact summary."""
        if not setups:
            return f"📭 No {title} found."

        msg = f"{title}\n━━━━━━━━━━━━━━━━━━━━━\n\n"

        for setup in setups[:10]:  # Limit to 10
            dir_emoji = "🟢" if setup.direction == TradeDirection.BUY else "🔴"
            grade = setup.score_breakdown.grade.value if setup.score_breakdown else "?"
            score = setup.score_breakdown.total_score if setup.score_breakdown else 0
            setup_type = setup.score_breakdown.setup_type.value if setup.score_breakdown else ""

            msg += (
                f"{dir_emoji} {setup.symbol} | {setup.timeframe} | "
                f"{setup.direction.value}\n"
                f"   Entry: {setup.entry} | SL: {setup.stop_loss} | "
                f"TP: {setup.take_profit}\n"
                f"   RRR: 1:{setup.risk_reward_ratio} | "
                f"Score: {score} | Grade: {grade}\n"
                f"   Status: {setup_type}\n\n"
            )

        if len(setups) > 10:
            msg += f"\n... and {len(setups) - 10} more setups"

        return msg

    @staticmethod
    def format_pair_analysis(symbol: str, result: ScanResult) -> str:
        """Format detailed analysis for a single pair."""
        # Filter zones and setups for this symbol
        sym_zones = [z for z in result.all_zones if z.symbol == symbol]
        sym_setups = [s for s in result.valid_setups if s.symbol == symbol]

        if not sym_zones and not sym_setups:
            return f"📭 No data available for {symbol}."

        msg = f"📊 PAIR ANALYSIS: {symbol}\n━━━━━━━━━━━━━━━━━━━━━\n\n"

        # Fresh Support zones
        fresh_support = [
            z for z in sym_zones
            if z.zone_type == ZoneType.SUPPORT
            and z.classification in (ZoneClassification.FRESH_CLEAN, ZoneClassification.FRESH)
        ]
        msg += f"🟢 Fresh Support Zones: {len(fresh_support)}\n"
        for z in fresh_support[:3]:
            msg += f"   {z.zone_bottom:.5f} - {z.zone_top:.5f} ({z.timeframe})\n"

        # Fresh Resistance zones
        fresh_resistance = [
            z for z in sym_zones
            if z.zone_type == ZoneType.RESISTANCE
            and z.classification in (ZoneClassification.FRESH_CLEAN, ZoneClassification.FRESH)
        ]
        msg += f"\n🔴 Fresh Resistance Zones: {len(fresh_resistance)}\n"
        for z in fresh_resistance[:3]:
            msg += f"   {z.zone_bottom:.5f} - {z.zone_top:.5f} ({z.timeframe})\n"

        # Touch counts
        msg += f"\n📍 Zone Touch Summary:\n"
        for z in sym_zones[:5]:
            msg += f"   {z.zone_type.value} ({z.timeframe}): {z.touch_count} touches\n"

        # Active setups
        if sym_setups:
            msg += f"\n⚡ Active Setups:\n"
            for s in sym_setups[:3]:
                dir_emoji = "🟢" if s.direction == TradeDirection.BUY else "🔴"
                msg += (
                    f"   {dir_emoji} {s.direction.value} | "
                    f"Entry: {s.entry} | SL: {s.stop_loss} | TP: {s.take_profit}\n"
                    f"   RRR: 1:{s.risk_reward_ratio} | "
                    f"Score: {s.score_breakdown.total_score if s.score_breakdown else 0} | "
                    f"Grade: {s.score_breakdown.grade.value if s.score_breakdown else '?'}\n"
                    f"   Type: {s.score_breakdown.setup_type.value if s.score_breakdown else 'N/A'}\n\n"
                )
        else:
            msg += "\n📭 No active trade setups.\n"

        return msg

    @staticmethod
    def format_help() -> str:
        """Format help message."""
        return (
            "🤖 MSNR TRADING AGENT - COMMANDS\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "/scan - Scan all symbols and show active setups\n\n"
            "/fresh - Show all Fresh Clean zones\n\n"
            "/nonfresh - Show all Non-Fresh zones\n\n"
            "/sniper - Show only Sniper setups\n\n"
            "/watchlist - Show only Grade A and A+ setups\n\n"
            "/pair SYMBOL - Detailed analysis for a symbol\n"
            "  Example: /pair EURUSD\n\n"
            "/alerts - Enable or disable alerts\n\n"
            "/help - Show this help message\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 Supported Markets:\n"
            "  • Forex (Major + Minor pairs)\n"
            "  • Metals (XAUUSD)\n"
            "  • Crypto (BTC, ETH, SOL, XRP, BNB...)\n\n"
            "⏰ Timeframes: M15, H1, H4\n\n"
            "🎯 Scoring: Max 100 points\n"
            "  • Fresh Zone: +40\n"
            "  • Zero Touches: +20\n"
            "  • Strong Departure: +30\n"
            "  • H4 Alignment: +10\n"
            "  • Liquidity Sweep: +10\n"
            "  • BOS: +10\n"
            "  • FVG: +10\n\n"
            "📈 Grades:\n"
            "  • A+ (90-100) | A (70-89) | B (50-69)\n"
            "  • Below 50 = Ignored\n"
        )
