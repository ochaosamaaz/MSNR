"""
Telegram Bot Module.

Implements all bot commands:
- /scan - Scan all symbols and show active setups
- /fresh - Show all Fresh Clean zones
- /nonfresh - Show all Non-Fresh zones
- /sniper - Show only Sniper setups
- /watchlist - Show only Grade A and A+ setups
- /pair SYMBOL - Detailed analysis for a symbol
- /alerts - Enable or disable alerts
- /help - Show all commands
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from msnr_bot.config import Config
from msnr_bot.modules.scanner import MarketScanner, ScanResult
from msnr_bot.bot.formatter import MessageFormatter

logger = logging.getLogger(__name__)


class MSNRBot:
    """
    Telegram Bot for MSNR Trading Agent.
    """

    def __init__(self, scanner: MarketScanner):
        self.scanner = scanner
        self.formatter = MessageFormatter()
        self.alerts_enabled = Config.ALERTS_ENABLED
        self._app: Optional[Application] = None
        self._last_scan: Optional[ScanResult] = None

    def build_application(self) -> Application:
        """Build and configure the Telegram bot application."""
        self._app = (
            Application.builder()
            .token(Config.TELEGRAM_BOT_TOKEN)
            .build()
        )

        # Register command handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("scan", self._cmd_scan))
        self._app.add_handler(CommandHandler("fresh", self._cmd_fresh))
        self._app.add_handler(CommandHandler("nonfresh", self._cmd_nonfresh))
        self._app.add_handler(CommandHandler("sniper", self._cmd_sniper))
        self._app.add_handler(CommandHandler("watchlist", self._cmd_watchlist))
        self._app.add_handler(CommandHandler("pair", self._cmd_pair))
        self._app.add_handler(CommandHandler("alerts", self._cmd_alerts))
        self._app.add_handler(CommandHandler("budget", self._cmd_budget))

        return self._app

    # ─────────────────────────────────────────────
    # COMMAND HANDLERS
    # ─────────────────────────────────────────────

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        welcome = (
            "🤖 MSNR Trading Agent Active!\n\n"
            "Malaysia SNR methodology for:\n"
            "• Forex (Major + Minor)\n"
            "• Metals (XAUUSD)\n"
            "• Crypto (BTC, ETH, SOL, XRP, BNB...)\n\n"
            "Use /help to see all commands.\n"
            "Use /scan to start scanning markets."
        )
        await update.message.reply_text(welcome)

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await update.message.reply_text(self.formatter.format_help())

    async def _cmd_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /scan command - scan all symbols."""
        await update.message.reply_text("🔍 Scanning all markets... This may take a moment.")

        try:
            result = await self.scanner.scan_all()
            self._last_scan = result

            # Send summary
            await update.message.reply_text(self.formatter.format_scan_summary(result))

            # Send valid setups if any
            if result.valid_setups:
                msg = self.formatter.format_setups_list(
                    result.valid_setups, "✅ ACTIVE SETUPS"
                )
                await self._send_long_message(update, msg)
            else:
                await update.message.reply_text("📭 No valid setups at this time.")

        except Exception as e:
            logger.error(f"Scan error: {e}")
            await update.message.reply_text(f"❌ Scan error: {str(e)[:200]}")

    async def _cmd_fresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /fresh command - show fresh zones."""
        if not self._last_scan:
            await update.message.reply_text(
                "⚠️ No scan data. Run /scan first."
            )
            return

        msg = self.formatter.format_fresh_zones(self._last_scan.fresh_zones)
        await self._send_long_message(update, msg)

    async def _cmd_nonfresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /nonfresh command - show non-fresh zones."""
        if not self._last_scan:
            await update.message.reply_text(
                "⚠️ No scan data. Run /scan first."
            )
            return

        msg = self.formatter.format_non_fresh_zones(self._last_scan.non_fresh_zones)
        await self._send_long_message(update, msg)

    async def _cmd_sniper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sniper command - show sniper setups only."""
        if not self._last_scan:
            await update.message.reply_text(
                "⚠️ No scan data. Run /scan first."
            )
            return

        setups = self._last_scan.sniper_setups
        if not setups:
            await update.message.reply_text("📭 No Sniper setups at this time.")
            return

        # Send each sniper setup as a full alert
        for setup in setups[:5]:
            msg = self.formatter.format_setup_alert(setup)
            await update.message.reply_text(msg)

    async def _cmd_watchlist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /watchlist command - show A and A+ setups."""
        if not self._last_scan:
            await update.message.reply_text(
                "⚠️ No scan data. Run /scan first."
            )
            return

        setups = self._last_scan.watchlist_setups
        msg = self.formatter.format_setups_list(setups, "👀 WATCHLIST (Grade A & A+)")
        await self._send_long_message(update, msg)

    async def _cmd_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pair SYMBOL command - detailed pair analysis."""
        if not context.args:
            await update.message.reply_text(
                "⚠️ Please specify a symbol.\n"
                "Example: /pair EURUSD"
            )
            return

        symbol = context.args[0].upper()

        # Validate symbol
        all_symbols = Config.all_symbols()
        if symbol not in all_symbols:
            await update.message.reply_text(
                f"❌ Unknown symbol: {symbol}\n\n"
                f"Supported symbols include:\n"
                f"Forex: {', '.join(Config.FOREX_MAJORS[:5])}...\n"
                f"Crypto: {', '.join(Config.CRYPTO[:5])}...\n"
                f"Metals: {', '.join(Config.METALS)}"
            )
            return

        await update.message.reply_text(f"🔍 Analyzing {symbol}...")

        try:
            # Run scan for this specific symbol
            result = await self.scanner.scan_symbol(symbol)

            msg = self.formatter.format_pair_analysis(symbol, result)
            await self._send_long_message(update, msg)

            # Send full alerts for valid setups
            for setup in result.valid_setups[:3]:
                alert_msg = self.formatter.format_setup_alert(setup)
                await update.message.reply_text(alert_msg)

        except Exception as e:
            logger.error(f"Pair analysis error for {symbol}: {e}")
            await update.message.reply_text(f"❌ Error analyzing {symbol}: {str(e)[:200]}")

    async def _cmd_alerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /alerts command - toggle alerts."""
        self.alerts_enabled = not self.alerts_enabled
        status = "ENABLED ✅" if self.alerts_enabled else "DISABLED ❌"
        await update.message.reply_text(
            f"🔔 Alerts: {status}\n\n"
            f"{'Automatic alerts will be sent for new high-quality setups.' if self.alerts_enabled else 'No automatic alerts will be sent.'}"
        )

    async def _cmd_budget(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /budget command - show API usage stats."""
        stats = self.scanner.data_fetcher.get_cache_stats()
        remaining = self.scanner.data_fetcher.remaining_budget
        total = 780

        # Visual budget bar
        used_pct = ((total - remaining) / total) * 100
        bar_len = 20
        filled = int(bar_len * used_pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)

        await update.message.reply_text(
            f"💰 API BUDGET STATUS\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{stats}\n\n"
            f"Usage: [{bar}] {used_pct:.0f}%\n\n"
            f"📋 Cost per action:\n"
            f"  /scan = ~12 requests\n"
            f"  /pair = 3 requests\n"
            f"  Auto-alert = ~12 requests\n\n"
            f"💡 Cache saves requests!\n"
            f"H4 data cached 4 hours, H1 cached 1 hour."
        )

    # ─────────────────────────────────────────────
    # ALERT SENDING (for automatic notifications)
    # ─────────────────────────────────────────────

    async def send_alert(self, message: str, chat_id: Optional[str] = None):
        """Send an alert message to the configured chat."""
        if not self.alerts_enabled:
            return

        target_chat = chat_id or Config.TELEGRAM_CHAT_ID
        if not target_chat:
            logger.warning("No chat ID configured for alerts")
            return

        if self._app and self._app.bot:
            try:
                await self._app.bot.send_message(
                    chat_id=target_chat,
                    text=message,
                )
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")

    async def send_setup_alert(self, setup, chat_id: Optional[str] = None):
        """Send a formatted setup alert."""
        msg = self.formatter.format_setup_alert(setup)
        await self.send_alert(msg, chat_id)

    # ─────────────────────────────────────────────
    # UTILITIES
    # ─────────────────────────────────────────────

    async def _send_long_message(self, update: Update, text: str):
        """Send a message, splitting if too long for Telegram (4096 char limit)."""
        max_len = 4000

        if len(text) <= max_len:
            await update.message.reply_text(text)
            return

        # Split into chunks
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break

            # Find a good split point
            split_idx = text.rfind("\n\n", 0, max_len)
            if split_idx == -1:
                split_idx = text.rfind("\n", 0, max_len)
            if split_idx == -1:
                split_idx = max_len

            chunks.append(text[:split_idx])
            text = text[split_idx:].lstrip("\n")

        for chunk in chunks:
            if chunk.strip():
                await update.message.reply_text(chunk)
