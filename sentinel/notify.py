import requests
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _send(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[NOTIFY] Telegram credentials not set — skipping send.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[NOTIFY] Telegram send failed: {e}")
        return False


def send_signal_alert(symbol: str, signal: str, price: float, entry: float,
                      target: float, stop: float, confidence: int,
                      reasoning: str, rr: float) -> bool:
    emoji = {"STRONG BUY": "🟢🔥", "BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(signal, "⚪")
    text = (
        f"{emoji} <b>SENTINEL — {signal}</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<b>Symbol:</b> {symbol}\n"
        f"<b>Price:</b> ${price:.2f}\n"
        f"<b>Entry:</b> ${entry:.2f}  |  <b>Target:</b> ${target:.2f}  |  <b>Stop:</b> ${stop:.2f}\n"
        f"<b>R:R</b> 1:{rr:.1f}  |  <b>Confidence:</b> {confidence}/100\n"
        f"<b>Reason:</b> {reasoning}\n"
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M ET')}</i>"
    )
    return _send(text)


def send_portfolio_alert(symbol: str, event: str, price: float,
                         entry: float, pnl_pct: float) -> bool:
    emoji = "🎯" if event == "TARGET HIT" else "🛑"
    text = (
        f"{emoji} <b>PORTFOLIO — {event}</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<b>Symbol:</b> {symbol}\n"
        f"<b>Current Price:</b> ${price:.2f}  |  <b>Entry:</b> ${entry:.2f}\n"
        f"<b>P&L:</b> {pnl_pct:+.2f}%\n"
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M ET')}</i>"
    )
    return _send(text)


def send_scan_summary(buys: list, sells: list, scan_time: str) -> bool:
    lines = [f"📊 <b>SENTINEL SCAN SUMMARY — {scan_time}</b>\n━━━━━━━━━━━━━━━━━"]

    if buys:
        lines.append(f"\n🟢 <b>Top Buys ({len(buys)})</b>")
        for s in buys[:5]:
            lines.append(
                f"  • <b>{s['symbol']}</b> [{s['signal']}] "
                f"${s['price']:.2f} — {s['confidence']}/100 — {s['reasoning']}"
            )

    if sells:
        lines.append(f"\n🔴 <b>Top Sells ({len(sells)})</b>")
        for s in sells[:3]:
            lines.append(
                f"  • <b>{s['symbol']}</b> [{s['signal']}] "
                f"${s['price']:.2f} — {s['confidence']}/100 — {s['reasoning']}"
            )

    if not buys and not sells:
        lines.append("\nNo actionable signals this scan.")

    return _send("\n".join(lines))


def send_test_message() -> bool:
    text = (
        "✅ <b>Sentinel Lite — System Check</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        "Telegram connection <b>confirmed</b>.\n"
        "Ready to receive trading signals.\n"
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M ET')}</i>"
    )
    ok = _send(text)
    print(f"[NOTIFY] Test message {'sent successfully' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    send_test_message()
