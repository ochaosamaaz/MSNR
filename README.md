# MSNR Telegram Trading Agent

A professional-grade Telegram trading bot that implements the **Malaysia SNR (Support & Resistance) methodology** to scan Forex, Gold, and Crypto markets, detect high-quality trade setups, and deliver real-time alerts.

## Features

### Market Coverage
- **Forex**: All Major pairs (EUR/USD, GBP/USD, USD/JPY, etc.) + All Minor pairs
- **Metals**: XAU/USD (Gold)
- **Crypto**: BTC, ETH, SOL, XRP, BNB, ADA, DOGE, AVAX, DOT, LINK

### Timeframes
- M15 (15-minute)
- H1 (1-hour)
- H4 (4-hour)

### Core Analysis
- **SNR Zone Detection** — Swing highs/lows with configurable buffers
- **Zone Classification** — Fresh Clean, Fresh, Non-Fresh (First Retest), Expired
- **Departure Strength** — Strong (≥3 ATR), Medium (≥2 ATR), Weak (<2 ATR)
- **Touch Counting** — Tracks how many times price retests a zone

### Confluence Factors
- **Liquidity Sweep** — Detects price sweeps above/below swing points
- **Break of Structure (BOS)** — Identifies structural breaks
- **Fair Value Gap (FVG)** — Finds imbalances in price
- **H4 Trend Alignment** — EMA crossover + structure analysis
- **Multi-Timeframe Alignment** — Zones confirmed across timeframes

### Scoring System (Max 100)
| Factor | Points |
|--------|--------|
| Fresh Zone | +40 |
| Zero Touches | +20 |
| Strong Departure | +30 |
| H4 Alignment | +10 |
| Liquidity Sweep | +10 |
| BOS | +10 |
| FVG | +10 |

### Grading
| Grade | Score Range |
|-------|-------------|
| A+ | 90-100 |
| A | 70-89 |
| B | 50-69 |
| Ignore | Below 50 |

### Setup Classifications
- **SNIPER** — Fresh Clean + Sweep + BOS + FVG + MTF Alignment + Score ≥ 95
- **HIGH PROBABILITY** — Fresh Clean + Sweep + BOS + FVG + Score ≥ 90
- **VALID** — Fresh Clean + Score ≥ 70 + RRR ≥ 1.5 + SL ≤ 50 pips

### Risk Management
- Maximum Stop Loss: 50 pips (Forex/Metals)
- Minimum Risk-Reward Ratio: 1.5
- SL Buffer: 5-10 pips (configurable)
- TP Target: Nearest valid SNR level

---

## Installation

### Prerequisites
- Python 3.10+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- TwelveData API Key (free tier: 800 req/day) — for Forex/Metals data

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/MSNR.git
cd MSNR

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Configuration (.env)

```env
# Required
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional (for Forex/Metals data)
TWELVEDATA_API_KEY=your_api_key

# Scanning
SCAN_INTERVAL_MINUTES=5

# Risk Management
MAX_SL_PIPS=50
MIN_RRR=1.5
SL_BUFFER_PIPS=7

# Alerts
ALERTS_ENABLED=true
MIN_SCORE_ALERT=70
```

### Run

```bash
python main.py
```

---

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/scan` | Scan all symbols and show active setups |
| `/fresh` | Show all Fresh Clean zones |
| `/nonfresh` | Show all Non-Fresh (First Retest) zones |
| `/sniper` | Show only Sniper setups |
| `/watchlist` | Show only Grade A and A+ setups |
| `/pair SYMBOL` | Detailed analysis for a specific pair |
| `/alerts` | Toggle automatic alerts on/off |
| `/help` | Show all commands and scoring info |

### Example: `/pair EURUSD`
Returns:
- Fresh Support zones
- Fresh Resistance zones
- Touch Count for each zone
- Active setups with SL, TP, RRR, Score, Grade

---

## Alert Format

```
🚨 MSNR SNIPER SETUP
━━━━━━━━━━━━━━━━━━━━━

PAIR:
EURUSD

TIMEFRAME:
H1

TYPE:
🟢 BUY

ENTRY:
1.12450

STOP LOSS:
1.11950

SL DISTANCE:
50 Pips

TAKE PROFIT:
1.13450

TP TARGET:
Nearest Resistance

RISK REWARD:
1:2.0

━━━━━━━━━━━━━━━━━━━━━

ZONE:
FRESH CLEAN SUPPORT

TOUCH COUNT:
0

DEPARTURE:
STRONG

SWEEP:
YES

BOS:
YES

FVG:
YES

━━━━━━━━━━━━━━━━━━━━━

SCORE:
95

GRADE:
A+

STATUS:
SNIPER SETUP
━━━━━━━━━━━━━━━━━━━━━
```

---

## Architecture

```
msnr_bot/
├── __init__.py
├── config.py              # Central configuration
├── core/
│   ├── snr_engine.py      # SNR zone detection engine
│   ├── confluence.py      # Confluence factors (Sweep, BOS, FVG, Trend)
│   ├── scoring.py         # Scoring and grading system
│   └── trade_setup.py     # Trade calculator (SL, TP, RRR)
├── modules/
│   ├── data_fetcher.py    # Market data (CCXT + TwelveData)
│   └── scanner.py         # Market scanner orchestrator
├── bot/
│   ├── telegram_bot.py    # Telegram bot commands
│   ├── alert_system.py    # Automatic alert scheduling
│   └── formatter.py       # Message formatting
└── data/                  # Data storage
```

---

## Data Sources

| Market | Source | API Key Required |
|--------|--------|-----------------|
| Crypto | CCXT (Binance) | No (public data) |
| Forex | TwelveData | Yes (free tier) |
| Metals | TwelveData | Yes (free tier) |

---

## Alert Rules

### Sends alerts when:
- ✅ New Fresh Clean Support detected
- ✅ New Fresh Clean Resistance detected
- ✅ First Retest detected
- ✅ High Probability Setup detected
- ✅ Sniper Setup detected

### Does NOT alert when:
- ❌ Touch Count > 1 (Expired)
- ❌ Score below 70
- ❌ Risk Reward below 1.5
- ❌ Stop Loss above 50 pips

---

## License

MIT License

---

## Disclaimer

This bot is for educational and informational purposes only. It does not constitute financial advice. Trading forex, metals, and cryptocurrencies carries significant risk. Always do your own research and risk management before trading.
