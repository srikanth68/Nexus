"""
data.py — hybrid data layer
  Finnhub /quote  → real-time price, open, prev-close  (free tier)
  yfinance        → daily candles for indicators, market cap, beta, earnings
"""

import time
import requests
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import date, timedelta
import pytz

from config import FINNHUB_TOKEN

BASE = "https://finnhub.io/api/v1"
EST  = pytz.timezone("America/New_York")

# ── Finnhub (real-time quote only) ────────────────────────────────────────────

def _fh_quote(symbol: str) -> dict | None:
    try:
        r = requests.get(f"{BASE}/quote",
                         params={"symbol": symbol, "token": FINNHUB_TOKEN},
                         timeout=8)
        r.raise_for_status()
        d = r.json()
        return d if d.get("c", 0) > 0 else None
    except Exception as e:
        print(f"[DATA] {symbol} quote error: {e}")
        return None

# ── Indicator math ─────────────────────────────────────────────────────────────

def _rsi(closes: pd.Series, period: int = 14) -> float:
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    val   = (100 - 100 / (1 + rs)).iloc[-1]
    return round(float(val), 2)


def _macd(closes: pd.Series):
    e12  = closes.ewm(span=12, adjust=False).mean()
    e26  = closes.ewm(span=26, adjust=False).mean()
    line = e12 - e26
    sig  = line.ewm(span=9, adjust=False).mean()
    hist = line - sig
    crossover = bool(hist.iloc[-1] > 0 and hist.iloc[-2] <= 0)
    bullish   = crossover or bool(hist.iloc[-1] > 0)
    return (round(float(line.iloc[-1]), 4),
            round(float(sig.iloc[-1]), 4),
            round(float(hist.iloc[-1]), 4),
            bullish, crossover)


def _sma(closes: pd.Series, period: int) -> float:
    return float(closes.rolling(period).mean().iloc[-1])


def _vwap(df: pd.DataFrame) -> float:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return float((tp * df["Volume"]).cumsum().iloc[-1] /
                 df["Volume"].cumsum().iloc[-1])

# ── Public API ─────────────────────────────────────────────────────────────────

def get_spy_context() -> dict:
    try:
        spy   = yf.Ticker("SPY")
        intra = spy.history(period="1d", interval="5m")
        q     = _fh_quote("SPY")

        price = q["c"] if q else (float(intra["Close"].iloc[-1]) if not intra.empty else None)
        if price is None:
            return {"above_vwap": True, "trending_up": True}

        if not intra.empty:
            vwap  = _vwap(intra)
            trend = price > float(intra["Close"].iloc[0])
        else:
            vwap  = price
            trend = True

        return {
            "price":       round(price, 2),
            "vwap":        round(vwap, 2),
            "above_vwap":  price > vwap,
            "trending_up": trend,
        }
    except Exception as e:
        print(f"[DATA] SPY context error: {e}")
        return {"above_vwap": True, "trending_up": True}


def get_stock_data(symbol: str) -> dict | None:
    try:
        t     = yf.Ticker(symbol)
        info  = t.info
        daily = t.history(period="3mo", interval="1d")

        if daily.empty or len(daily) < 30:
            return None

        closes  = daily["Close"]
        volumes = daily["Volume"]

        # ── Real-time price from Finnhub (fallback: yfinance last close) ──────
        q = _fh_quote(symbol)
        if q:
            price      = q["c"]
            open_price = q["o"]
            prev_close = q["pc"]
        else:
            price      = float(closes.iloc[-1])
            open_price = float(daily["Open"].iloc[-1])
            prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else price

        gap_pct    = (open_price - prev_close) / prev_close * 100 if prev_close else 0
        avg_volume = float(volumes.iloc[-20:].mean())
        market_cap = info.get("marketCap") or 0
        beta       = info.get("beta") or 1.0

        # ── Indicators ────────────────────────────────────────────────────────
        rsi = _rsi(closes)
        macd_val, macd_sig, macd_hist, macd_bullish, macd_crossover = _macd(closes)
        sma20 = _sma(closes, 20)
        sma50 = _sma(closes, 50)

        # ATR
        hl    = daily["High"] - daily["Low"]
        atr   = float(hl.iloc[-14:].mean())
        stop_dist = min(atr * 0.5, 2.5)
        stop      = round(price - stop_dist, 2)
        target    = round(price + stop_dist * 2, 2)
        rr        = round((target - price) / stop_dist, 2) if stop_dist > 0 else 0

        uptrend = price > sma50 and sma20 > sma50

        # ── Intraday VWAP (yfinance 5m) ───────────────────────────────────────
        intra = t.history(period="1d", interval="5m")
        if not intra.empty:
            vwap       = _vwap(intra)
            above_vwap = price > vwap
            intra_vol  = float(intra["Volume"].sum())
            bars       = len(intra)
            expected   = avg_volume * (bars / 78)
            vol_vs_avg = intra_vol / expected if expected > 0 else 1.0
        else:
            vwap       = price
            above_vwap = price > open_price   # proxy: above open = intraday trend up
            vol_vs_avg = float(volumes.iloc[-1]) / avg_volume if avg_volume > 0 else 1.0

        # ── Earnings ──────────────────────────────────────────────────────────
        earnings_soon = False
        try:
            cal = t.calendar
            if cal is not None and not cal.empty:
                earn_date = pd.to_datetime(cal.iloc[0, 0]).date()
                earnings_soon = abs((earn_date - date.today()).days) <= 5
        except Exception:
            pass

        return {
            "symbol":         symbol,
            "price":          round(price, 2),
            "prev_close":     round(prev_close, 2),
            "open":           round(open_price, 2),
            "gap_pct":        round(gap_pct, 2),
            "avg_volume":     int(avg_volume),
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
