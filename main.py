"""
MSNR Telegram Trading Agent - Main Entry Point.

Malaysia SNR methodology-based trading bot that:
- Scans Forex, Gold, and Crypto markets
- Detects SNR zones (Support & Resistance)
- Classifies Fresh and Non-Fresh zones
- Calculates Stop Loss and Take Profit
- Scores setup quality
- Sends high-quality trade alerts via Telegram

Usage:
    python main.py
"""

import asyncio
import logging
import sys

from msnr_bot.config import Config
from msnr_bot.modules.scanner import MarketScanner
from msnr_bot.bot.telegram_bot import MSNRBot
from msnr_bot.bot.alert_system import AlertSystem

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("msnr_bot.log", mode="a"),
    ],
)

logger = logging.getLogger("msnr_bot")


def validate_config():
    """Validate required configuration."""
    if not Config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set. Check your .env file.")
        sys.exit(1)

    if not Config.TELEGRAM_CHAT_ID:
        logger.warning(
            "TELEGRAM_CHAT_ID not set. Automatic alerts will not work. "
            "Bot commands will still function."
        )

    logger.info("Configuration validated successfully.")
    logger.info(f"  Scan Interval: {Config.SCAN_INTERVAL_MINUTES} minutes")
    logger.info(f"  Alerts Enabled: {Config.ALERTS_ENABLED}")
    logger.info(f"  Min Score: {Config.MIN_SCORE_ALERT}")
    logger.info(f"  Max SL: {Config.MAX_SL_PIPS} pips")
    logger.info(f"  Min RRR: {Config.MIN_RRR}")
    logger.info(f"  Symbols: {len(Config.all_symbols())} total")
    logger.info(f"  Timeframes: {Config.TIMEFRAMES}")


def main():
    """Main application entry point."""
    logger.info("=" * 50)
    logger.info("MSNR TELEGRAM TRADING AGENT v1.0.0")
    logger.info("Malaysia SNR Methodology")
    logger.info("=" * 50)

    # Validate configuration
    validate_config()

    # Initialize components
    scanner = MarketScanner()
    bot = MSNRBot(scanner)
    alert_system = AlertSystem(scanner, bot.send_alert)

    # Build the Telegram application
    app = bot.build_application()

    # Set up post-init to start alert system
    async def post_init(application):
        """Start alert system after bot is initialized."""
        if Config.ALERTS_ENABLED and Config.TELEGRAM_CHAT_ID:
            alert_system.start()
            logger.info("Automatic alert system started.")
        else:
            logger.info("Automatic alerts disabled (no CHAT_ID or alerts disabled).")

    async def post_shutdown(application):
        """Cleanup on shutdown."""
        alert_system.stop()
        await scanner.close()
        logger.info("Bot shutdown complete.")

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    # Run the bot
    logger.info("Starting Telegram bot... (Press Ctrl+C to stop)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
