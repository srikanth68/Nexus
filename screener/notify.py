import requests
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _send(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[NOTIFY] Telegram not configured.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[NOTIFY] Failed: {e}")
        return False


def send_signals(signals: list[dict], scan_time: str):
    if not signals:
        _send(
            f"📭 <b>NEXUS Screener — {scan_time}</b>\n"
            "No stocks passed all filters today.\n"
            "<i>Market may be choppy or SPY is red.</i>"
        )
        return

    lines = [f"⚡ <b>NEXUS — Trade Ideas</b>  {scan_time}\n"
             f"━━━━━━━━━━━━━━━━━━━━━"]

    for s in signals:
        lines.append(
            f"\n🟢 <b>{s['symbol']}</b>  [{s['strategy']}]\n"
            f"  Entry <b>${s['entry']:.2f}</b>  "
            f"Stop <b>${s['stop']:.2f}</b>  "
            f"Target <b>${s['target']:.2f}</b>\n"
            f"  R:R <b>1:{s['rr']}</b>  "
            f"Conf <b>{s['confidence']}/100</b>\n"
            f"  <i>{s['reasoning']}</i>"
        )

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━\n{len(signals)} signal(s) today")
    _send("\n".join(lines))
