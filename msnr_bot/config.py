"""Configuration module for MSNR Trading Agent."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Central configuration for the MSNR Trading Agent."""

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # Data Sources
    TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

    # Scanning
    SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "5"))

    # Zone Configuration
    ZONE_BUFFER_ATR_MULTIPLIER = float(os.getenv("ZONE_BUFFER_ATR_MULTIPLIER", "0.1"))
    SL_BUFFER_PIPS = int(os.getenv("SL_BUFFER_PIPS", "7"))
    MAX_SL_PIPS = int(os.getenv("MAX_SL_PIPS", "50"))
    MIN_RRR = float(os.getenv("MIN_RRR", "1.5"))

    # Alert Configuration
    ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "true").lower() == "true"
    MIN_SCORE_ALERT = int(os.getenv("MIN_SCORE_ALERT", "70"))

    # Swing Detection
    SWING_LEFT_BARS = 2
    SWING_RIGHT_BARS = 2

    # Departure Thresholds (in ATR multiples)
    DEPARTURE_STRONG = 3.0
    DEPARTURE_MEDIUM = 2.0

    # Scoring Weights
    SCORE_FRESH_ZONE = 40
    SCORE_TOUCH_ZERO = 20
    SCORE_STRONG_DEPARTURE = 30
    SCORE_H4_ALIGNMENT = 10
    SCORE_LIQUIDITY_SWEEP = 10
    SCORE_BOS = 10
    SCORE_FVG = 10
    MAX_SCORE = 100

    # Grade Thresholds
    GRADE_A_PLUS_MIN = 90
    GRADE_A_MIN = 70
    GRADE_B_MIN = 50

    # Timeframes
    TIMEFRAMES = ["M15", "H1", "H4"]

    # Symbols
    FOREX_MAJORS = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"
    ]

    FOREX_MINORS = [
        "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
        "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
        "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
        "NZDJPY", "NZDCHF", "NZDCAD",
        "CADJPY", "CADCHF", "CHFJPY"
    ]

    METALS = ["XAUUSD"]

    CRYPTO = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
        "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"
    ]

    @classmethod
    def all_symbols(cls):
        """Return all tradeable symbols."""
        return cls.FOREX_MAJORS + cls.FOREX_MINORS + cls.METALS + cls.CRYPTO

    @classmethod
    def get_pip_value(cls, symbol: str) -> float:
        """Get pip value for a symbol."""
        if symbol in cls.CRYPTO:
            return 1.0  # USDT based
        elif "JPY" in symbol:
            return 0.01
        elif symbol == "XAUUSD":
            return 0.1
        else:
            return 0.0001

    @classmethod
    def get_symbol_category(cls, symbol: str) -> str:
        """Get category for a symbol."""
        if symbol in cls.FOREX_MAJORS:
            return "FOREX_MAJOR"
        elif symbol in cls.FOREX_MINORS:
            return "FOREX_MINOR"
        elif symbol in cls.METALS:
            return "METALS"
        elif symbol in cls.CRYPTO:
            return "CRYPTO"
        return "UNKNOWN"
