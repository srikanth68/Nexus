"""
run_scan.py — entry point called by cron
Usage:
  python run_scan.py deep       # full deep scan of all symbols
  python run_scan.py portfolio  # portfolio monitor only
  python run_scan.py both       # deep scan + portfolio monitor
"""

import sys
from datetime import datetime
import pytz

from config import CONFIDENCE_ALERT_THRESHOLD, validate
from scanner import run_full_scan, get_premarket_movers
from portfolio import monitor_portfolio
from notion_writer import write_signals_batch
from notify import send_signal_alert, send_scan_summary


EST = pytz.timezone("America/New_York")


def is_market_hours() -> bool:
    now = datetime.now(EST)
    if now.weekday() >= 5:
        return False
    open_time  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_time = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_time <= now <= close_time


# ── TradingView MCP bridge ────────────────────────────────────────────────────
# If TradingView MCP is running in your Claude session, data will flow through.
# Otherwise scanner falls back to yfinance automatically.

def tradingview_fetcher(symbol: str) -> dict | None:
    """
    Hook for TradingView MCP data. When running inside Claude Code with the
    TradingView MCP active, this can be replaced with a real MCP call.
    Returns None here so yfinance fallback is used for standalone cron runs.
    """
    return None


# ── deep scan ─────────────────────────────────────────────────────────────────

def do_deep_scan():
    scan_time = datetime.now(EST).strftime("%Y-%m-%d %H:%M ET")
    print(f"\n{'='*50}")
    print(f"[RUN] Deep scan started — {scan_time}")
    print(f"{'='*50}")

    # grab pre-market movers before market opens
    now = datetime.now(EST)
    extras = []
    if now.hour < 10:
        print("[RUN] Fetching pre-market movers...")
        extras = get_premarket_movers()
        if extras:
            print(f"[RUN] Extra symbols: {extras}")

    results = run_full_scan(extra_symbols=extras, mcp_fetcher=tradingview_fetcher)

    # split into actionable signals
    buys  = [r for r in results if r["signal"] in ("STRONG BUY", "BUY")]
    sells = [r for r in results if r["signal"] == "SELL"]

    # write all non-HOLD signals to Notion
    to_write = buys + sells
    if to_write:
        write_signals_batch(to_write)

    # send individual Telegram alerts for high-confidence signals
    for r in results:
        if r["confidence"] >= CONFIDENCE_ALERT_THRESHOLD and r["signal"] != "HOLD":
            send_signal_alert(
                symbol=r["symbol"], signal=r["signal"], price=r["price"],
                entry=r["entry"], target=r["target"], stop=r["stop"],
                confidence=r["confidence"], reasoning=r["reasoning"], rr=r["rr"],
            )

    # send summary message
    send_scan_summary(buys, sells, scan_time)

    print(f"\n[RUN] Scan complete — {len(buys)} buys, {len(sells)} sells, {len(results)} total")
    for r in results[:5]:
        print(f"  {r['symbol']:6s} {r['signal']:10s} conf={r['confidence']:3d}  {r['reasoning']}")

    return results


# ── portfolio monitor ─────────────────────────────────────────────────────────

def do_portfolio_monitor():
    print(f"\n[RUN] Portfolio monitor — {datetime.now(EST).strftime('%H:%M ET')}")
    events = monitor_portfolio()
    if events:
        print(f"[RUN] Events fired: {[e['event'] for e in events]}")
    else:
        print("[RUN] No stop/target hits.")
    return events


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "deep"

    if not validate():
        print("[RUN] Config validation failed — check your .env file.")
        sys.exit(1)

    if mode == "deep":
        do_deep_scan()
    elif mode == "portfolio":
        do_portfolio_monitor()
    elif mode == "both":
        do_deep_scan()
        do_portfolio_monitor()
    else:
        print(f"Unknown mode '{mode}'. Use: deep | portfolio | both")
        sys.exit(1)
