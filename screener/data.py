"""
data.py — market data via Twelve Data (quotes + history, no yfinance)
Finnhub free /calendar/earnings kept for earnings check only.
"""

import time
import requests
import numpy as np
from datetime import date, timedelta
import pytz

from config import TWELVE_DATA_KEY, FINNHUB_TOKEN

TD_BASE = "https://api.twelvedata.com"
FH_BASE = "https://finnhub.io/api/v1"
EST     = pytz.timezone("America/New_York")

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _td(path: str, params: dict) -> dict:
    params["apikey"] = TWELVE_DATA_KEY
    r = requests.get(TD_BASE + path, params=params, timeout=12)
    r.raise_for_status()
    return r.json()


def _fh(path: str, params: dict) -> dict:
    params["token"] = FINNHUB_TOKEN
    r = requests.get(FH_BASE + path, params=params, timeout=8)
    r.raise_for_status()
    return r.json()

# ── Indicator math (pure numpy, no yfinance/pandas) ───────────────────────────

def _closes_from_ts(values: list) -> list[float]:
    """Twelve Data time_series values are newest-first; reverse to oldest-first."""
    return [float(v["close"]) for v in reversed(values)]


def _rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    delta = np.diff(closes)
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    ag, al = np.mean(gain[:period]), np.mean(loss[:period])
    for i in range(period, len(gain)):
        ag = (ag * (period - 1) + gain[i]) / period
        al = (al * (period - 1) + loss[i]) / period
    rs = ag / al if al != 0 else 1e9
    return round(100 - 100 / (1 + rs), 2)


def _ema(closes: list, span: int) -> list:
    k, out = 2 / (span + 1), [closes[0]]
    for c in closes[1:]:
        out.append(c * k + out[-1] * (1 - k))
    return out


def _macd(closes: list):
    if len(closes) < 35:
        return 0.0, 0.0, 0.0, False, False
    e12  = _ema(closes, 12)
    e26  = _ema(closes, 26)
    line = [a - b for a, b in zip(e12, e26)]
    sig  = _ema(line, 9)
    hist = [a - b for a, b in zip(line, sig)]
    cross   = hist[-1] > 0 and hist[-2] <= 0
    bullish = cross or hist[-1] > 0
    return round(line[-1], 4), round(sig[-1], 4), round(hist[-1], 4), bullish, cross


def _sma(closes: list, period: int) -> float:
    return float(np.mean(closes[-period:])) if len(closes) >= period else closes[-1]


def _atr(values: list, period: int = 14) -> float:
    bars = list(reversed(values))[-period:]   # oldest-first, last N bars
    hl   = [float(b["high"]) - float(b["low"]) for b in bars]
    return float(np.mean(hl)) if hl else 1.0

# ── Batch fetchers (1 request for all symbols) ────────────────────────────────

def _batch_quotes(symbols: list) -> dict:
    """Returns {SYMBOL: quote_dict} for all symbols in one request."""
    sym_str = ",".join(symbols)
    data    = _td("/quote", {"symbol": sym_str})
    # Single symbol → wrap in dict; batch → already dict keyed by symbol
    if symbols and "symbol" in data:
        return {data["symbol"]: data}
    return data   # {AAPL: {...}, MSFT: {...}, ...}


def _batch_time_series(symbols: list, outputsize: int = 90) -> dict:
    """Returns {SYMBOL: [values...]} for all symbols in one request."""
    sym_str = ",".join(symbols)
    data    = _td("/time_series",
                  {"symbol": sym_str, "interval": "1day",
                   "outputsize": outputsize})
    # Single symbol returns {"meta": ..., "values": [...]}
    if "values" in data:
        sym = symbols[0]
        return {sym: data["values"]}
    # Batch returns {AAPL: {"meta": ..., "values": [...]}, ...}
    return {sym: v.get("values", []) for sym, v in data.items()
            if isinstance(v, dict) and "values" in v}

# ── Earnings (Finnhub free) ────────────────────────────────────────────────────

def _earnings_soon(symbol: str, window: int = 5) -> bool:
    if not FINNHUB_TOKEN:
        return False
    today = date.today()
    try:
        data = _fh("/calendar/earnings",
                   {"symbol": symbol,
                    "from":   today.strftime("%Y-%m-%d"),
                    "to":     (today + timedelta(days=window)).strftime("%Y-%m-%d")})
        return len(data.get("earningsCalendar", [])) > 0
    except Exception:
        return False

# ── Public API ─────────────────────────────────────────────────────────────────

def get_spy_context(quotes: dict, series: dict) -> dict:
    try:
        q = quotes.get("SPY", {})
        v = series.get("SPY", [])
        price = float(q.get("close") or q.get("price") or 0)
        if price == 0 or not v:
            return {"above_vwap": True, "trending_up": True}

        closes   = _closes_from_ts(v)
        open_px  = float(q.get("open", closes[-1]))
        sma20    = _sma(closes, 20)

        return {
            "price":       round(price, 2),
            "vwap":        round(sma20, 2),   # SMA20 as VWAP proxy for daily context
            "above_vwap":  price > sma20,
            "trending_up": price > open_px,
        }
    except Exception as e:
        print(f"[DATA] SPY context error: {e}")
        return {"above_vwap": True, "trending_up": True}


def load_all_data(universe: list) -> tuple[dict, dict]:
    """
    Fetch quotes + time series for all symbols in 2 API requests.
    Returns (quotes_dict, series_dict).
    Twelve Data free = 8 req/min, 800 credits/day.
    Two batch calls use 2 requests + len(universe)*2 credits.
    """
    print(f"[DATA] Fetching quotes for {len(universe)} symbols...")
    quotes = _batch_quotes(universe)
    time.sleep(8)   # stay under 8 req/min

    print(f"[DATA] Fetching 90-day history for {len(universe)} symbols...")
    series = _batch_time_series(universe, outputsize=90)
    time.sleep(8)

    return quotes, series


def get_stock_data(symbol: str, q: dict, v: list) -> dict | None:
    """Build a screening dict from pre-fetched quote + time series data."""
    try:
        if not q or not v or len(v) < 30:
            return None

        # ── Price fields ───────────────────────────────────────────────────────
        price      = float(q.get("close") or q.get("price") or 0)
        open_price = float(q.get("open", price))
        prev_close = float(q.get("previous_close", price))
        avg_vol    = float(q.get("average_volume") or 0)
        if price == 0:
            return None

        gap_pct  = (open_price - prev_close) / prev_close * 100 if prev_close else 0

        # Derive avg_volume from history if not in quote
        if avg_vol == 0:
            vols   = [float(bar["volume"]) for bar in v[:20]]
            avg_vol = float(np.mean(vols)) if vols else 0

        # ── Indicators ────────────────────────────────────────────────────────
        closes = _closes_from_ts(v)
        rsi    = _rsi(closes)
        macd_val, macd_sig, macd_hist, macd_bullish, macd_crossover = _macd(closes)
        sma20  = _sma(closes, 20)
        sma50  = _sma(closes, 50)
        atr    = _atr(v)

        stop_dist  = min(atr * 0.5, 2.5)
        stop       = round(price - stop_dist, 2)
        target     = round(price + stop_dist * 2, 2)
        rr         = round((target - price) / stop_dist, 2) if stop_dist > 0 else 0
        uptrend    = price > sma50 and sma20 > sma50

        # VWAP proxy: price above today's open = intraday uptrend
        above_vwap  = price > open_price
        vwap_proxy  = round(open_price, 2)

        # Volume spike: today vs 20-day avg (from most recent bar)
        today_vol  = float(v[0].get("volume", 0))   # v[0] is newest
        vol_vs_avg = today_vol / avg_vol if avg_vol > 0 else 1.0

        # Market cap / beta — Twelve Data statistics (best-effort, non-blocking)
        market_cap = 0
        beta       = 1.0
        try:
            stats = _td("/statistics", {"symbol": symbol})
            vc    = stats.get("valuations_and_metrics", {})
            market_cap = float(vc.get("market_capitalization", 0) or 0) * 1_000_000
            beta       = float(vc.get("beta", 1.0) or 1.0)
            time.sleep(1)
        except Exception:
            pass

        return {
            "symbol":         symbol,
            "price":          round(price, 2),
            "prev_close":     round(prev_close, 2),
            "open":           round(open_price, 2),
            "gap_pct":        round(gap_pct, 2),
            "avg_volume":     int(avg_vol),
            "vol_vs_avg":     round(vol_vs_avg, 2),
            "market_cap":     market_cap,
            "beta":           round(beta, 2),
            "rsi":            rsi,
            "macd_val":       macd_val,
            "macd_sig":       macd_sig,
            "macd_hist":      macd_hist,
            "macd_bullish":   macd_bullish,
            "macd_crossover": macd_crossover,
            "sma20":          round(sma20, 2),
            "sma50":          round(sma50, 2),
            "vwap":           vwap_proxy,
            "above_vwap":     above_vwap,
            "uptrend":        uptrend,
            "earnings_soon":  _earnings_soon(symbol),
            "stop":           stop,
            "target":         target,
            "stop_dist":      round(stop_dist, 2),
            "rr":             rr,
            "atr":            round(atr, 2),
        }
    except Exception as e:
        print(f"[DATA] {symbol}: {e}")
        return None
