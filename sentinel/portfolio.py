"""
portfolio.py — monitor open positions, fire stop/target alerts
"""

import yfinance as yf
from datetime import datetime
from notion_writer import get_open_positions, update_position
from notify import send_portfolio_alert


def _get_current_price(symbol: str) -> float | None:
    try:
        t = yf.Ticker(symbol)
        price = t.fast_info.get("lastPrice") or t.fast_info.get("regularMarketPrice")
        return float(price) if price else None
    except Exception as e:
        print(f"[PORTFOLIO] Price fetch failed for {symbol}: {e}")
        return None


def monitor_portfolio() -> list[dict]:
    """
    Check all open positions. Fire alerts and close out hits.
    Returns list of events that occurred.
    """
    positions = get_open_positions()
    if not positions:
        print("[PORTFOLIO] No open positions found.")
        return []

    events = []
    for pos in positions:
        sym    = pos["symbol"]
        entry  = pos.get("entry")
        stop   = pos.get("stop")
        target = pos.get("target")
        page_id = pos["page_id"]

        if not sym or not entry:
            continue

        price = _get_current_price(sym)
        if price is None:
            print(f"[PORTFOLIO] Could not get price for {sym}, skipping.")
            continue

        pnl_pct = round((price - entry) / entry * 100, 2) if entry else 0
        print(f"[PORTFOLIO] {sym}: ${price:.2f}  PnL: {pnl_pct:+.2f}%")

        # ── stop hit ──────────────────────────────────────────────────
        if stop and price <= stop:
            print(f"[PORTFOLIO] 🛑 STOP HIT: {sym} @ ${price:.2f} (stop: ${stop:.2f})")
            send_portfolio_alert(sym, "STOP HIT", price, entry, pnl_pct)
            update_position(page_id, pnl_pct=pnl_pct, status="closed")
            events.append({"symbol": sym, "event": "STOP HIT", "price": price, "pnl_pct": pnl_pct})

        # ── target hit ────────────────────────────────────────────────
        elif target and price >= target:
            print(f"[PORTFOLIO] 🎯 TARGET HIT: {sym} @ ${price:.2f} (target: ${target:.2f})")
            send_portfolio_alert(sym, "TARGET HIT", price, entry, pnl_pct)
            update_position(page_id, pnl_pct=pnl_pct, status="closed")
            events.append({"symbol": sym, "event": "TARGET HIT", "price": price, "pnl_pct": pnl_pct})

        # ── still open, update P&L ────────────────────────────────────
        else:
            update_position(page_id, pnl_pct=pnl_pct)

    return events


def get_portfolio_summary() -> dict:
    """Return summary stats for dashboard."""
    positions = get_open_positions()
    total_pnl = sum(p.get("pnl_pct") or 0 for p in positions)
    winners   = [p for p in positions if (p.get("pnl_pct") or 0) > 0]
    losers    = [p for p in positions if (p.get("pnl_pct") or 0) < 0]
    return {
        "open_count":  len(positions),
        "total_pnl":   round(total_pnl, 2),
        "winners":     len(winners),
        "losers":      len(losers),
        "positions":   positions,
        "as_of":       datetime.utcnow().isoformat(),
    }


if __name__ == "__main__":
    print("=== Portfolio Monitor Test ===")
    summary = get_portfolio_summary()
    print(f"Open positions : {summary['open_count']}")
    print(f"Total P&L      : {summary['total_pnl']:+.2f}%")
    print(f"Winners/Losers : {summary['winners']}/{summary['losers']}")
    if summary["positions"]:
        print("\nPositions:")
        for p in summary["positions"]:
            print(f"  {p['symbol']:6s}  entry=${p['entry']:.2f}  "
                  f"stop=${p['stop']:.2f}  target=${p['target']:.2f}  "
                  f"pnl={p['pnl_pct']:+.2f}%")
    else:
        print("No open positions in Notion (add some via Notion UI or notion_writer.add_position)")
