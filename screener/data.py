"""
data.py — market data layer using Finnhub real-time REST API
"""

import time
import requests
import numpy as np
from datetime import datetime, timedelta, date
import pytz

from config import FINNHUB_TOKEN

BASE  = "https://finnhub.io/api/v1"
EST   = pytz.timezone("America/New_York")

# ── HTTP helper ────────────────────────────────────────────────────────────────

def _get(path: str, params: dict) -> dict:
    params["token"] = FINNHUB_TOKEN
    r = requests.get(BASE + path, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

# ── Indicator math ─────────────────────────────────────────────────────────────

def _rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    delta = np.diff(closes)
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    avg_g = np.mean(gain[:period])
    avg_l = np.mean(loss[:period])
    for i in range(period, len(gain)):
        avg_g = (avg_g * (period - 1) + gain[i]) / period
        avg_l = (avg_l * (period - 1) + loss[i]) / period
    rs = avg_g / avg_l if avg_l != 0 else 1e9
    return round(100 - 100 / (1 + rs), 2)


def _ema(closes: list, span: int) -> list:
    k   = 2 / (span + 1)
    ema = [closes[0]]
    for c in closes[1:]:
        ema.append(c * k + ema[-1] * (1 - k))
    return ema


def _macd(closes: list):
    if len(closes) < 35:
        return 0.0, 0.0, 0.0, False, False
    e12   = _ema(closes, 12)
    e26   = _ema(closes, 26)
    line  = [a - b for a, b in zip(e12, e26)]
    sig   = _ema(line, 9)
    hist  = [a - b for a, b in zip(line, sig)]
    crossover = hist[-1] > 0 and hist[-2] <= 0
    bullish   = crossover or hist[-1] > 0
    return (round(line[-1], 4), round(sig[-1], 4),
            round(hist[-1], 4), bullish, crossover)


def _sma(closes: list, period: int) -> float:
    return float(np.mean(closes[-period:])) if len(closes) >= period else float(closes[-1])


def _vwap(highs, lows, closes, volumes) -> float:
    tp  = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    cum_tpv = sum(t * v for t, v in zip(tp, volumes))
    cum_vol  = sum(volumes)
    return cum_tpv / cum_vol if cum_vol > 0 else closes[-1]

# ── Finnhub data fetchers ──────────────────────────────────────────────────────

def _daily_candles(symbol: str, days: int = 90) -> dict | None:
    to_ts   = int(datetime.now().timestamp())
    from_ts = int((datetime.now() - timedelta(days=days)).timestamp())
    data    = _get("/stock/candle", {"symbol": symbol, "resolution": "D",
                                     "from": from_ts, "to": to_ts})
    return data if data.get("s") == "ok" else None


def _intraday_candles(symbol: str) -> dict | None:
    now     = datetime.now(EST)
    # start of trading day in ET → midnight UTC offset
    sod     = now.replace(hour=9, minute=30, second=0, microsecond=0)
    from_ts = int(sod.timestamp())
    to_ts   = int(now.timestamp())
    data    = _get("/stock/candle", {"symbol": symbol, "resolution": "5",
                                     "from": from_ts, "to": to_ts})
    return data if data.get("s") == "ok" else None


def _quote(symbol: str) -> dict | None:
    data = _get("/quote", {"symbol": symbol})
    return data if data.get("c", 0) > 0 else None


def _metrics(symbol: str) -> dict:
    data = _get("/stock/metric", {"symbol": symbol, "metric": "all"})
    m    = data.get("metric", {})
    series = data.get("series", {}).get("annual", {})
    # market cap not in free metric — use 52w shares * price approximation, or 0
    mkt_cap = m.get("marketCapitalization", 0) or 0
    beta    = m.get("beta", 1.0) or 1.0
    return {"market_cap": mkt_cap * 1_000_000, "beta": beta}


def _earnings_soon(symbol: str, window: int = 5) -> bool:
    today = date.today()
    frm   = today.strftime("%Y-%m-%d")
    to    = (today + timedelta(days=window)).strftime("%Y-%m-%d")
    try:
        data = _get("/calendar/earnings", {"symbol": symbol, "from": frm, "to": to})
        return len(data.get("earningsCalendar", [])) > 0
    except Exception:
        return False

# ── Public API ─────────────────────────────────────────────────────────────────

def get_spy_context() -> dict:
    try:
        q    = _quote("SPY")
        intra = _intraday_candles("SPY")
        if not q:
            return {"above_vwap": True, "trending_up": True}
        price = q["c"]
        if intra:
            vwap = _vwap(intra["h"], intra["l"], intra["c"], intra["v"])
            above = price > vwap
            trend = price > intra["c"][0]
        else:
            above, trend = True, True
            vwap = price
        return {"price": price, "vwap": round(vwap, 2),
                "above_vwap": above, "trending_up": trend}
    except Exception as e:
        print(f"[DATA] SPY context error: {e}")
        return {"above_vwap": True, "trending_up": True}


def get_stock_data(symbol: str) -> dict | None:
    try:
        # ── 1. Real-time quote ─────────────────────────────────────────────────
        q = _quote(symbol)
        if not q:
            return None
        price      = q["c"]    # current price
        open_price = q["o"]    # day open
        prev_close = q["pc"]   # previous close
        gap_pct    = (open_price - prev_close) / prev_close * 100 if prev_close else 0

        # ── 2. Daily candles (90 days for indicators) ──────────────────────────
        daily = _daily_candles(symbol)
        if not daily or len(daily["c"]) < 30:
            return None
        closes  = daily["c"]
        volumes = daily["v"]
        highs   = daily["h"]
        lows    = daily["l"]
        avg_volume = float(np.mean(volumes[-20:]))

        # ── 3. Indicators ──────────────────────────────────────────────────────
        rsi = _rsi(closes)
        macd_val, macd_sig, macd_hist, macd_bullish, macd_crossover = _macd(closes)
        sma20 = _sma(closes, 20)
        sma50 = _sma(closes, 50)

        # ATR (14-day)
        atr_vals = [highs[i] - lows[i] for i in range(-14, 0)]
        atr      = float(np.mean(atr_vals))
        stop_dist = min(atr * 0.5, 2.5)
        stop      = round(price - stop_dist, 2)
        target    = round(price + stop_dist * 2, 2)
        rr        = round((target - price) / stop_dist, 2) if stop_dist > 0 else 0

        uptrend = price > sma50 and sma20 > sma50

        # ── 4. Intraday VWAP + today's volume ─────────────────────────────────
        intra = _intraday_candles(symbol)
        if intra and intra["c"]:
            vwap       = _vwap(intra["h"], intra["l"], intra["c"], intra["v"])
            above_vwap = price > vwap
            intra_vol  = float(sum(intra["v"]))
            bars_today = len(intra["c"])
            expected   = avg_volume * (bars_today / 78)
            vol_vs_avg = intra_vol / expected if expected > 0 else 1.0
        else:
            vwap       = price
            above_vwap = True
            vol_vs_avg = volumes[-1] / avg_volume if avg_volume > 0 else 1.0

        # ── 5. Fundamentals ────────────────────────────────────────────────────
        time.sleep(0.2)   # stay under 60 req/min across 5 calls per symbol
        fund = _metrics(symbol)

        # ── 6. Earnings ────────────────────────────────────────────────────────
        earnings_soon = _earnings_soon(symbol)

        return {
            "symbol":         symbol,
            "price":          round(price, 2),
            "prev_close":     round(prev_close, 2),
            "open":           round(open_price, 2),
            "gap_pct":        round(gap_pct, 2),
            "avg_volume":     int(avg_volume),
            "vol_vs_avg":     round(vol_vs_avg, 2),
            "market_cap":     fund["market_cap"],
            "beta":           round(fund["beta"], 2),
            "rsi":            rsi,
            "macd_val":       macd_val,
            "macd_sig":       macd_sig,
            "macd_hist":      macd_hist,
            "macd_bullish":   macd_bullish,
            "macd_crossover": macd_crossover,
            "sma20":          round(sma20, 2),
            "sma50":          round(sma50, 2),
            "vwap":           round(vwap, 2),
            "above_vwap":     above_vwap,
            "uptrend":        uptrend,
            "earnings_soon":  earnings_soon,
            "stop":           stop,
            "target":         target,
            "stop_dist":      round(stop_dist, 2),
            "rr":             rr,
            "atr":            round(atr, 2),
        }
    except Exception as e:
        print(f"[DATA] {symbol}: {e}")
        return None
