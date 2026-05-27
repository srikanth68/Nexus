import os
from dotenv import load_dotenv
load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# Finnhub
FINNHUB_TOKEN = os.getenv("FINNHUB_TOKEN", "")

# ── Screening filters ────────────────────────────────────────────────────────
MIN_PRICE          = 15.0
MAX_PRICE          = 150.0
MIN_AVG_VOLUME     = 1_000_000
MIN_MARKET_CAP     = 5_000_000_000   # $5B
MAX_BETA           = 2.0
MAX_STOP_DISTANCE  = 3.0             # $ per share
MIN_RISK_REWARD    = 2.0
RSI_LOW            = 35
RSI_HIGH           = 65
VOLUME_SPIKE       = 1.5             # 1.5x avg volume
MAX_GAP_UP_PCT     = 4.0             # ignore gaps > 4%
EARNINGS_WINDOW    = 5               # days

# ── Stock universe ───────────────────────────────────────────────────────────
# Liquid, high-cap stocks worth scanning every day
UNIVERSE = [
    # Mega cap tech
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","AMD","TSLA","AVGO","ORCL",
    # Financials
    "JPM","BAC","GS","MS","V","MA","AXP","BLK","C","WFC",
    # Large cap growth
    "CRM","SHOP","SNOW","PLTR","UBER","LYFT","RBLX","COIN","HOOD","SQ",
    # ETFs (market context + tradeable)
    "SPY","QQQ","IWM","XLK","XLF","SOXX",
    # Healthcare & energy
    "UNH","LLY","MRK","CVX","XOM","OXY",
    # Consumer
    "AMZN","HD","NKE","SBUX","MCD","TGT","COST",
    # Semis
    "MU","QCOM","INTC","TSM","AMAT","KLAC","LRCX",
]
UNIVERSE = list(dict.fromkeys(UNIVERSE))  # dedupe
