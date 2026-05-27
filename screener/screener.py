"""
screener.py — applies ALL signal conditions, returns qualified tickers only.
A signal is only generated if EVERY condition passes.
"""

from config import (
    MIN_PRICE, MAX_PRICE, MIN_AVG_VOLUME, MIN_MARKET_CAP,
    MAX_BETA, MAX_STOP_DISTANCE, MIN_RISK_REWARD,
    RSI_LOW, RSI_HIGH, VOLUME_SPIKE, MAX_GAP_UP_PCT, UNIVERSE
)
from data import get_stock_data, get_spy_context


def _check(symbol: str, d: dict, spy: dict) -> dict | None:
    """
    Run every condition. Returns signal dict if ALL pass, else None.
    Logs which condition failed for debugging.
    """
    fails = []

    # ── MARKET CONTEXT — check SPY first ─────────────────────────────────────
    if not spy.get("above_vwap") and not spy.get("trending_up"):
        print(f"[SCREEN] {symbol}: SKIP — SPY red and below VWAP")
        return None

    # ── PRICE & LIQUIDITY ─────────────────────────────────────────────────────
    if not (MIN_PRICE <= d["price"] <= MAX_PRICE):
        fails.append(f"price ${d['price']} out of ${MIN_PRICE}-${MAX_PRICE}")

    if d["avg_volume"] < MIN_AVG_VOLUME:
        fails.append(f"avg vol {d['avg_volume']:,} < {MIN_AVG_VOLUME:,}")

    if d["market_cap"] < MIN_MARKET_CAP:
        fails.append(f"mkt cap ${d['market_cap']/1e9:.1f}B < $5B")

    if d["earnings_soon"]:
        fails.append("earnings within 5 days")

    # ── RISK ──────────────────────────────────────────────────────────────────
    if d["beta"] >= MAX_BETA:
        fails.append(f"beta {d['beta']} >= {MAX_BETA}")

    if d["stop_dist"] >= MAX_STOP_DISTANCE:
        fails.append(f"stop dist ${d['stop_dist']} >= ${MAX_STOP_DISTANCE}")

    if d["rr"] < MIN_RISK_REWARD:
        fails.append(f"R:R {d['rr']} < {MIN_RISK_REWARD}")

    # ── TECHNICALS ────────────────────────────────────────────────────────────
    if not (RSI_LOW <= d["rsi"] <= RSI_HIGH):
        fails.append(f"RSI {d['rsi']} out of {RSI_LOW}-{RSI_HIGH}")

    if not d["macd_bullish"]:
        fails.append("MACD not bullish")

    if not d["above_vwap"]:
        fails.append(f"price ${d['price']} below VWAP ${d['vwap']}")

    if d["price"] < d["sma20"] * 0.99:   # 1% buffer for "just reclaimed"
        fails.append(f"price ${d['price']} below SMA20 ${d['sma20']}")

    if d["vol_vs_avg"] < VOLUME_SPIKE:
        fails.append(f"volume {d['vol_vs_avg']:.1f}x avg (need {VOLUME_SPIKE}x)")

    # ── GAP CHECK ─────────────────────────────────────────────────────────────
    if d["gap_pct"] > MAX_GAP_UP_PCT:
        fails.append(f"gap up {d['gap_pct']:.1f}% > {MAX_GAP_UP_PCT}% (chasing)")

    # ── TREND ─────────────────────────────────────────────────────────────────
    if not d["uptrend"]:
        fails.append("no uptrend / base breakout on daily")

    if fails:
        print(f"[SCREEN] {symbol}: FAIL — {' | '.join(fails)}")
        return None

    # ── ALL CONDITIONS MET — build signal ─────────────────────────────────────
    confidence = _confidence(d, spy)
    strategy   = _strategy_label(d)
    reasoning  = _reasoning(d, spy)

    print(f"[SCREEN] {symbol}: ✓ SIGNAL — conf={confidence} {strategy}")

    return {
        "symbol":     d["symbol"],
        "signal":     "BUY",
        "price":      d["price"],
        "entry":      d["price"],
        "stop":       d["stop"],
        "target":     d["target"],
        "rr":         d["rr"],
        "confidence": confidence,
        "strategy":   strategy,
        "reasoning":  reasoning,
    }


def _confidence(d: dict, spy: dict) -> int:
    score = 50  # base — already passed all hard filters

    # Bonus points for extra conviction
    if d["macd_crossover"]:           score += 10   # fresh crossover > just positive
    if d["rsi"] < 50:                 score += 5    # mild oversold is sweet spot
    if d["vol_vs_avg"] >= 2.0:        score += 10   # very strong volume
    elif d["vol_vs_avg"] >= 1.5:      score += 5
    if d["above_vwap"]:               score += 5
    if spy.get("above_vwap"):         score += 5
    if spy.get("trending_up"):        score += 5
    if d["price"] > d["sma50"]:       score += 5
    if d["gap_pct"] < 0:              score += 5    # gap down + setup = strong entry
    if d["rr"] >= 3.0:                score += 5    # better R:R

    return min(score, 99)


def _strategy_label(d: dict) -> str:
    if d["macd_crossover"] and d["rsi"] < 50 and d["vol_vs_avg"] >= 2.0:
        return "MACD Cross + Volume Surge"
    if d["gap_pct"] < -2 and d["above_vwap"]:
        return "Gap Down Reversal"
    if d["price"] > d["sma20"] and d["macd_bullish"]:
        return "SMA20 Reclaim + MACD"
    return "Multi-Factor Momentum"


def _reasoning(d: dict, spy: dict) -> str:
    parts = []
    parts.append(f"RSI {d['rsi']:.0f}")
    parts.append("MACD cross" if d["macd_crossover"] else "MACD bullish")
    parts.append(f"{'above' if d['above_vwap'] else 'reclaiming'} VWAP ${d['vwap']:.2f}")
    parts.append(f"vol {d['vol_vs_avg']:.1f}x avg")
    if spy.get("above_vwap"):
        parts.append("SPY green")
    if d["gap_pct"] < 0:
        parts.append(f"gap down {d['gap_pct']:.1f}% (support holding)")
    return " · ".join(parts)


def run_screen() -> list[dict]:
    print("\n[SCREEN] Checking SPY market context...")
    spy = get_spy_context()
    print(f"[SCREEN] SPY: ${spy.get('price','?'):.2f}  "
          f"VWAP ${spy.get('vwap','?'):.2f}  "
          f"above={'YES' if spy.get('above_vwap') else 'NO'}  "
          f"trending={'UP' if spy.get('trending_up') else 'DOWN'}")

    print(f"\n[SCREEN] Scanning {len(UNIVERSE)} symbols...\n")

    signals = []
    for sym in UNIVERSE:
        d = get_stock_data(sym)
        if d is None:
            print(f"[SCREEN] {sym}: no data")
            continue
        sig = _check(sym, d, spy)
        if sig:
            signals.append(sig)

    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return signals
