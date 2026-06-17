"""
Message Formatter for Telegram — Clean Modern UI.

Formats trade setups, zone information, and scan results
into beautiful Telegram messages.
"""

from typing import List

from msnr_bot.core.snr_engine import SNRZone, ZoneType, ZoneClassification, DepartureStrength
from msnr_bot.core.scoring import Grade, SetupType
from msnr_bot.core.trade_setup import TradeSetup, TradeDirection
from msnr_bot.modules.scanner import ScanResult


class MessageFormatter:
    """Formats data into clean Telegram messages."""

    @staticmethod
    def format_setup_alert(setup: TradeSetup) -> str:
        """Format a trade setup as a Telegram alert."""
        if not setup.score_breakdown:
            return ""

        # Header based on setup type
        if setup.score_breakdown.setup_type == SetupType.SNIPER:
            header = "🎯 SNIPER SETUP"
            bar = "▰▰▰▰▰▰▰▰▰▰"
        elif setup.score_breakdown.setup_type == SetupType.HIGH_PROBABILITY:
            header = "⚡ HIGH PROBABILITY"
            bar = "▰▰▰▰▰▰▰▰▰▱"
        else:
            header = "✅ VALID SETUP"
            bar = "▰▰▰▰▰▰▰▱▱▱"

        # Direction
        if setup.direction == TradeDirection.BUY:
            dir_icon = "🟢 BUY (Long)"
        else:
            dir_icon = "🔴 SELL (Short)"

        # Confluence checkmarks
        sweep = "✓" if setup._has_aligned_sweep() else "✗"
        bos = "✓" if setup._has_aligned_bos() else "✗"
        fvg = "✓" if setup._has_aligned_fvg() else "✗"

        # Zone info
        zone_text = ""
        if setup.zone:
            zone_text = (
                f"{setup.zone.classification.value} "
                f"{setup.zone.zone_type.value}"
            )

        msg = (
            f"{header}\n"
            f"{bar}\n"
            f"\n"
            f"{'═' * 24}\n"
            f"  {setup.symbol}  •  {setup.timeframe}\n"
            f"{'═' * 24}\n"
            f"\n"
            f"  {dir_icon}\n"
            f"\n"
            f"  ┌─ Trade Levels\n"
            f"  │  Entry     {setup.entry}\n"
            f"  │  Stop Loss {setup.stop_loss}\n"
            f"  │  Take Profit {setup.take_profit}\n"
            f"  └─\n"
            f"\n"
            f"  SL: {setup.sl_distance_pips} pips\n"
            f"  TP: {setup.tp_target_description}\n"
            f"  RRR: 1:{setup.risk_reward_ratio}\n"
            f"\n"
            f"{'─' * 24}\n"
            f"  Zone: {zone_text}\n"
            f"  Touches: {setup.zone.touch_count if setup.zone else 0}\n"
            f"  Departure: {setup.zone.departure_strength.value if setup.zone else '-'}\n"
            f"{'─' * 24}\n"
            f"  Sweep [{sweep}]  BOS [{bos}]  FVG [{fvg}]\n"
            f"{'─' * 24}\n"
            f"\n"
            f"  Score: {setup.score_breakdown.total_score}/100\n"
            f"  Grade: {setup.score_breakdown.grade.value}\n"
            f"  {setup.score_breakdown.setup_type.value}\n"
            f"\n"
            f"{'═' * 24}"
        )

        return msg

    @staticmethod
    def format_zone_info(zone: SNRZone) -> str:
        """Format a single zone compactly."""
        icon = "S" if zone.zone_type == ZoneType.SUPPORT else "R"
        fresh = "●" if zone.classification == ZoneClassification.FRESH_CLEAN else "○"

        return (
            f"  {fresh} [{icon}] {zone.zone_bottom:.5f} - {zone.zone_top:.5f} "
            f"({zone.timeframe}) | {zone.departure_strength.value}\n"
        )

    @staticmethod
    def format_fresh_zones(zones: List[SNRZone]) -> str:
        """Format list of fresh zones."""
        if not zones:
            return "No Fresh Clean zones detected."

        msg = (
            "FRESH CLEAN ZONES\n"
            "━━━━━━━━━━━━━━━━━\n\n"
        )

        # Group by symbol
        symbols = {}
        for zone in zones:
            if zone.symbol not in symbols:
                symbols[zone.symbol] = []
            symbols[zone.symbol].append(zone)

        for symbol, sym_zones in sorted(symbols.items()):
            support = [z for z in sym_zones if z.zone_type == ZoneType.SUPPORT]
            resistance = [z for z in sym_zones if z.zone_type == ZoneType.RESISTANCE]

            msg += f"┌ {symbol}\n"
            if support:
                msg += f"│ 🟢 Support ({len(support)})\n"
                for z in support[:3]:
                    msg += f"│ {MessageFormatter.format_zone_info(z)}"
            if resistance:
                msg += f"│ 🔴 Resistance ({len(resistance)})\n"
                for z in resistance[:3]:
                    msg += f"│ {MessageFormatter.format_zone_info(z)}"
            msg += "└\n\n"

        return msg

    @staticmethod
    def format_non_fresh_zones(zones: List[SNRZone]) -> str:
        """Format list of non-fresh zones."""
        if not zones:
            return "No Non-Fresh zones detected."

        msg = (
            "NON-FRESH ZONES (1st Retest)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        symbols = {}
        for zone in zones:
            if zone.symbol not in symbols:
                symbols[zone.symbol] = []
            symbols[zone.symbol].append(zone)

        for symbol, sym_zones in sorted(symbols.items()):
            msg += f"  {symbol}\n"
            for z in sym_zones[:4]:
                msg += MessageFormatter.format_zone_info(z)
            msg += "\n"

        return msg

    @staticmethod
    def format_scan_summary(result: ScanResult) -> str:
        """Format scan summary — clean and compact."""
        return (
            "┌─────────────────────────┐\n"
            "│    SCAN COMPLETE        │\n"
            "└─────────────────────────┘\n"
            f"\n"
            f"  Symbols: {result.symbols_scanned}\n"
            f"  Zones found: {len(result.all_zones)}\n"
            f"  Fresh: {len(result.fresh_zones)} | Non-Fresh: {len(result.non_fresh_zones)}\n"
            f"\n"
            f"  ✅ Valid Setups: {len(result.valid_setups)}\n"
            f"  🎯 Sniper: {len(result.sniper_setups)}\n"
            f"  ⚡ High Prob: {len(result.high_probability_setups)}\n"
            f"  👀 Watchlist: {len(result.watchlist_setups)}\n"
            f"\n"
            f"  {result.scan_time.strftime('%H:%M UTC • %d %b %Y')}"
        )

    @staticmethod
    def format_setups_list(setups: List[TradeSetup], title: str) -> str:
        """Format a list of setups compactly."""
        if not setups:
            return f"No {title} found."

        msg = f"{title}\n{'━' * 26}\n\n"

        for setup in setups[:8]:
            dir_icon = "🟢" if setup.direction == TradeDirection.BUY else "🔴"
            grade = setup.score_breakdown.grade.value if setup.score_breakdown else "?"
            score = setup.score_breakdown.total_score if setup.score_breakdown else 0

            msg += (
                f"{dir_icon} {setup.symbol} • {setup.timeframe} • {setup.direction.value}\n"
                f"   E: {setup.entry}  SL: {setup.stop_loss}  TP: {setup.take_profit}\n"
                f"   RRR 1:{setup.risk_reward_ratio} │ Score {score} │ {grade}\n"
                f"\n"
            )

        if len(setups) > 8:
            msg += f"  ... +{len(setups) - 8} more"

        return msg

    @staticmethod
    def format_pair_analysis(symbol: str, result: ScanResult) -> str:
        """Format detailed analysis for a single pair."""
        sym_zones = [z for z in result.all_zones if z.symbol == symbol]
        sym_setups = [s for s in result.valid_setups if s.symbol == symbol]

        if not sym_zones and not sym_setups:
            return f"No data available for {symbol}."

        msg = (
            f"┌─────────────────────────┐\n"
            f"│  {symbol:^23}│\n"
            f"└─────────────────────────┘\n\n"
        )

        # Fresh Support
        fresh_support = [
            z for z in sym_zones
            if z.zone_type == ZoneType.SUPPORT
            and z.classification in (ZoneClassification.FRESH_CLEAN, ZoneClassification.FRESH)
        ]
        msg += f"🟢 Support ({len(fresh_support)} fresh)\n"
        for z in fresh_support[:3]:
            msg += f"   {z.zone_bottom:.5f} - {z.zone_top:.5f} [{z.timeframe}]\n"
        if not fresh_support:
            msg += "   None\n"

        # Fresh Resistance
        fresh_resistance = [
            z for z in sym_zones
            if z.zone_type == ZoneType.RESISTANCE
            and z.classification in (ZoneClassification.FRESH_CLEAN, ZoneClassification.FRESH)
        ]
        msg += f"\n🔴 Resistance ({len(fresh_resistance)} fresh)\n"
        for z in fresh_resistance[:3]:
            msg += f"   {z.zone_bottom:.5f} - {z.zone_top:.5f} [{z.timeframe}]\n"
        if not fresh_resistance:
            msg += "   None\n"

        # Active setups
        if sym_setups:
            msg += f"\n{'─' * 26}\n"
            msg += f"⚡ Best Setup:\n\n"
            best = sym_setups[0]
            dir_icon = "🟢 BUY" if best.direction == TradeDirection.BUY else "🔴 SELL"
            msg += (
                f"   {dir_icon} • {best.timeframe}\n"
                f"   Entry:  {best.entry}\n"
                f"   SL:     {best.stop_loss} ({best.sl_distance_pips} pips)\n"
                f"   TP:     {best.take_profit}\n"
                f"   RRR:    1:{best.risk_reward_ratio}\n"
                f"   Score:  {best.score_breakdown.total_score if best.score_breakdown else 0}/100\n"
                f"   Grade:  {best.score_breakdown.grade.value if best.score_breakdown else '?'}\n"
            )
        else:
            msg += f"\n{'─' * 26}\n"
            msg += "   No active setups\n"

        return msg

    @staticmethod
    def format_help() -> str:
        """Format help message."""
        return (
            "┌─────────────────────────┐\n"
            "│   MSNR TRADING AGENT    │\n"
            "└─────────────────────────┘\n"
            "\n"
            "Commands:\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "\n"
            "/scan    Scan priority pairs\n"
            "/fresh   Fresh Clean zones\n"
            "/nonfresh  Non-Fresh zones\n"
            "/sniper  Sniper setups only\n"
            "/watchlist  Grade A & A+\n"
            "/pair SYMBOL  Analyze pair\n"
            "/alerts  Toggle auto-alerts\n"
            "/budget  API usage stats\n"
            "/help    This message\n"
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Markets: Forex • Gold • Crypto\n"
            "Timeframes: M15 • H1 • H4\n"
            "\n"
            "Scoring (max 100):\n"
            "  Fresh Zone    +40\n"
            "  Zero Touches  +20\n"
            "  Strong Depart +30\n"
            "  H4 Alignment  +10\n"
            "  Sweep/BOS/FVG +10 each\n"
            "\n"
            "Grades:\n"
            "  A+ = 90-100\n"
            "  A  = 70-89\n"
            "  B  = 50-69\n"
        )
