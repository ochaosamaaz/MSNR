"""
Automatic Alert System.

Monitors markets on a schedule and sends alerts when:
- New Fresh Clean Support detected
- New Fresh Clean Resistance detected
- First Retest detected
- High Probability Setup detected
- Sniper Setup detected

Does NOT alert for:
- Touch Count > 1
- Score below 70
- Risk Reward below 1.5
- Stop Loss above 50 pips
"""

import asyncio
import logging
from datetime import datetime
from typing import Set, Optional

from msnr_bot.config import Config
from msnr_bot.core.snr_engine import ZoneClassification, ZoneStatus
from msnr_bot.core.scoring import SetupType, Grade
from msnr_bot.core.trade_setup import TradeSetup
from msnr_bot.modules.scanner import MarketScanner, ScanResult
from msnr_bot.bot.formatter import MessageFormatter

logger = logging.getLogger(__name__)


class AlertSystem:
    """
    Automatic alert system that scans markets periodically
    and sends alerts for high-quality setups.
    """

    def __init__(self, scanner: MarketScanner, send_callback):
        """
        Args:
            scanner: MarketScanner instance
            send_callback: Async callback to send messages (bot.send_alert)
        """
        self.scanner = scanner
        self.send_callback = send_callback
        self.formatter = MessageFormatter()
        self.enabled = Config.ALERTS_ENABLED
        self._seen_setups: Set[str] = set()  # Track already-alerted setups
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self):
        """Start the alert monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Alert system started")

    def stop(self):
        """Stop the alert monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Alert system stopped")

    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._scan_and_alert()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Alert system error: {e}")

            # Wait for next scan interval
            await asyncio.sleep(Config.SCAN_INTERVAL_MINUTES * 60)

    async def _scan_and_alert(self):
        """Run a scan and send alerts for new setups."""
        logger.info("Alert system: Running scheduled scan...")

        try:
            result = await self.scanner.scan_all()
        except Exception as e:
            logger.error(f"Alert scan failed: {e}")
            return

        # Check for alertable setups
        new_alerts = 0

        for setup in result.valid_setups:
            if self._should_alert(setup):
                setup_key = self._get_setup_key(setup)

                # Skip if already alerted
                if setup_key in self._seen_setups:
                    continue

                # Send alert
                msg = self.formatter.format_setup_alert(setup)
                await self.send_callback(msg)
                self._seen_setups.add(setup_key)
                new_alerts += 1

                # Small delay between alerts
                await asyncio.sleep(1)

        # Alert for new fresh zones (without full setups)
        await self._alert_new_zones(result)

        if new_alerts > 0:
            logger.info(f"Alert system: Sent {new_alerts} new alerts")

        # Cleanup old seen setups (keep last 500)
        if len(self._seen_setups) > 500:
            # Convert to list, keep recent ones
            seen_list = list(self._seen_setups)
            self._seen_setups = set(seen_list[-300:])

    async def _alert_new_zones(self, result: ScanResult):
        """Alert for new fresh zones that don't have full trade setups."""
        for zone in result.fresh_zones:
            zone_key = f"zone_{zone.symbol}_{zone.timeframe}_{zone.zone_type.value}_{zone.swing_price}"

            if zone_key in self._seen_setups:
                continue

            # Only alert for Fresh Clean zones with strong departure
            if zone.classification != ZoneClassification.FRESH_CLEAN:
                continue

            msg = (
                f"✨ NEW FRESH CLEAN ZONE DETECTED\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"PAIR: {zone.symbol}\n"
                f"TIMEFRAME: {zone.timeframe}\n"
                f"TYPE: {zone.zone_type.value}\n"
                f"RANGE: {zone.zone_bottom:.5f} - {zone.zone_top:.5f}\n"
                f"DEPARTURE: {zone.departure_strength.value}\n"
                f"TOUCHES: {zone.touch_count}\n\n"
                f"⚠️ Monitor for entry confirmation."
            )

            await self.send_callback(msg)
            self._seen_setups.add(zone_key)
            await asyncio.sleep(0.5)

    def _should_alert(self, setup: TradeSetup) -> bool:
        """
        Determine if a setup should trigger an alert.

        Alerts ONLY when:
        - New Fresh Clean Support/Resistance detected
        - First Retest detected
        - High Probability Setup detected
        - Sniper Setup detected

        Does NOT alert for:
        - Touch Count > 1
        - Score below 70
        - Risk Reward below 1.5
        - Stop Loss above 50 pips
        """
        if not self.enabled:
            return False

        if not setup.is_valid:
            return False

        if not setup.score_breakdown:
            return False

        # Check score threshold
        if setup.score_breakdown.total_score < Config.MIN_SCORE_ALERT:
            return False

        # Check grade
        if setup.score_breakdown.grade in (Grade.B, Grade.IGNORE):
            return False

        # Check setup type
        if setup.score_breakdown.setup_type == SetupType.INVALID:
            return False

        # Check RRR
        if setup.risk_reward_ratio < Config.MIN_RRR:
            return False

        # Check SL for forex
        category = Config.get_symbol_category(setup.symbol)
        if category in ("FOREX_MAJOR", "FOREX_MINOR", "METALS"):
            if setup.sl_distance_pips > Config.MAX_SL_PIPS:
                return False

        # Check zone quality
        if setup.zone:
            if setup.zone.touch_count > 1:
                return False

        return True

    def _get_setup_key(self, setup: TradeSetup) -> str:
        """Generate a unique key for a setup to track if already alerted."""
        return (
            f"{setup.symbol}_{setup.timeframe}_{setup.direction.value}_"
            f"{setup.entry}_{setup.stop_loss}"
        )

    def toggle(self) -> bool:
        """Toggle alerts on/off. Returns new state."""
        self.enabled = not self.enabled
        return self.enabled

    @property
    def is_running(self) -> bool:
        """Check if alert system is running."""
        return self._running
