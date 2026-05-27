import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Notion
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_SIGNALS_DB_ID = os.getenv("NOTION_SIGNALS_DB_ID", "")
NOTION_PORTFOLIO_DB_ID = os.getenv("NOTION_PORTFOLIO_DB_ID", "")

# Watchlist — core + will be supplemented at runtime by pre-market movers
CORE_WATCHLIST = ["SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "AMZN", "META", "IWM"]

# Signal thresholds
CONFIDENCE_ALERT_THRESHOLD = 72   # min confidence to send Telegram alert

# Strategy parameters
RSI_OVERSOLD = 40
RSI_OVERBOUGHT = 70
RSI_NEUTRAL = 50
VOLUME_SPIKE_MULTIPLIER = 1.5     # current vol > 1.5x 20-day avg = spike

# Risk / reward
MIN_RISK_REWARD = 2.0             # 1:2 minimum
DEFAULT_STOP_PCT = 0.03           # 3% stop-loss below entry
DEFAULT_TARGET_PCT = 0.06         # 6% target (1:2 R:R)

# Pre-market mover filter
PREMARKET_MIN_VOLUME = 500_000
PREMARKET_MIN_CHANGE_PCT = 2.0

# Timezone
MARKET_TZ = "America/New_York"

def validate():
    missing = []
    for name, val in [
        ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
        ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
        ("NOTION_TOKEN", NOTION_TOKEN),
    ]:
        if not val:
            missing.append(name)
    if missing:
        print(f"[CONFIG] WARNING — missing env vars: {', '.join(missing)}")
        return False
    return True

if __name__ == "__main__":
    ok = validate()
    print(f"[CONFIG] Validation {'passed' if ok else 'failed (see above)'}")
    print(f"[CONFIG] Core watchlist: {CORE_WATCHLIST}")
    print(f"[CONFIG] Confidence threshold: {CONFIDENCE_ALERT_THRESHOLD}")
