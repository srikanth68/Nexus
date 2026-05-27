"""
data.py — market data layer using yfinance
Provides: price, OHLCV, indicators, VWAP, earnings calendar
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import pytz

EST = pytz.timezone("America/New_York")


def _rsi(closes: pd.Series, period: int = 14) -> float:
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return round(float((100 - 100 / (1 + rs)).iloc[-1]), 2)


def _macd(closes: pd.Series):
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    line  = ema12 - ema26
    sig   = line.ewm(span=9, adjust=False).mean()
    hist  = line - sig
    return float(line.iloc[-1]), float(sig.iloc[-1]), float(hist.iloc[-1])


def _sma(closes: pd.Series, period: int) -> float:
    return float(closes.rolling(period).mean().iloc[-1])


def _vwap(df_intraday: pd.DataFrame) -> float:
    """Calculate VWAP from intraday bars."""
    tp  = (df_intraday["High"] + df_intraday["Low"] + df_intraday["Close"]) / 3
    return float((tp * df_intraday["Volume"]).cumsum().iloc[-1] /
                 df_intraday["Volume"].cumsum().iloc[-1])


def get_spy_context() -> dict:
    """Check SPY: is it above VWAP and trending up?"""
    try:
        spy = yf.Ticker("SPY")
        df  = spy.history(period="1d", interval="5m")
        if df.empty:
            return {"above_vwap": True, "trending_up": True}  # assume ok if no data
        vwap  = _vwap(df)
        price = float(df["Close"].iloc[-1])
        prev  = float(df["Close"].iloc[0])
        return {
            "price":       price,
            "vwap":        vwap,
            "above_vwap":  price > vwap,
            "trending_up": price > prev,
        }
    except Exception as e:
        print(f"[DATA] SPY context error: {e}")
        return {"above_vwap": True, "trending_up": True}


def get_stock_data(symbol: str) -> dict | None:
    """
    Fetch all data needed for screening one symbol.
    Returns None if data is unavailable.
    """
    try:
        t    = yf.Ticker(symbol)
        info = t.info

        # ── Daily bars (3 months for indicators) ─────────────────────────────
        daily = t.history(period="3mo", interval="1d")
        if daily.empty or len(daily) < 30:
            return None

        closes  = daily["Close"]
        volumes = daily["Volume"]

        # ── Intraday bars (today, 5min for VWAP + intraday volume) ───────────
        intra = t.history(period="1d", interval="5m")

        # ── Fundamentals ──────────────────────────────────────────────────────
        price      = float(closes.iloc[-1])
        avg_volume = float(volumes.iloc[-20:].mean())
        market_cap = info.get("marketCap") or 0
        beta       = info.get("beta") or 1.0
        prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else price
        open_price = float(daily["Open"].iloc[-1])
        gap_pct    = (open_price - prev_close) / prev_close * 100

        # ── Indicators ────────────────────────────────────────────────────────
        rsi                       = _rsi(closes)
        macd_val, macd_sig, macd_hist = _macd(closes)
        sma20                     = _sma(closes, 20)
        sma50                     = _sma(closes, 50)

        # MACD crossover: histogram just turned positive (prev negative, now positive)
        macd_hist_prev = float((closes.ewm(span=12,adjust=False).mean() -
                                closes.ewm(span=26,adjust=False).mean() -
                                (closes.ewm(span=12,adjust=False).mean() -
                                 closes.ewm(span=26,adjust=False).mean()
                                ).ewm(span=9,adjust=False).mean()).iloc[-2]) \
                         if len(closes) > 27 else 0.0
        macd_crossover = macd_hist > 0 and macd_hist_prev <= 0
        macd_bullish   = macd_crossover or macd_hist > 0

        # VWAP
        if not intra.empty:
            vwap          = _vwap(intra)
            above_vwap    = price > vwap
            intra_vol     = float(intra["Volume"].sum())
            bars_today    = len(intra)
            # Compare to typical volume at this time of day using avg daily / 78 bars (6.5h * 12)
            expected_vol  = avg_volume * (bars_today / 78)
            vol_vs_avg    = intra_vol / expected_vol if expected_vol > 0 else 1.0
        else:
            vwap       = price
            above_vwap = True
            vol_vs_avg = float(volumes.iloc[-1]) / avg_volume if avg_volume > 0 else 1.0

        # ── Earnings check ────────────────────────────────────────────────────
        earnings_soon = False
        try:
            cal = t.calendar
            if cal is not None and not cal.empty:
                earn_date = pd.to_datetime(cal.iloc[0, 0]).date()
                days_away = abs((earn_date - date.today()).days)
                earnings_soon = days_away <= 5
        except Exception:
            pass

        # ── Trend: uptrend if price > SMA50 and SMA20 > SMA50 ───────────────
        uptrend = price > sma50 and sma20 > sma50

        # ── ATR for stop calculation ──────────────────────────────────────────
        high_low   = daily["High"] - daily["Low"]
        atr        = float(high_low.iloc[-14:].mean())
        stop_dist  = min(atr * 0.5, 2.5)   # half ATR, capped at $2.50
        stop       = round(price - stop_dist, 2)
        target     = round(price + stop_dist * 2, 2)  # 2:1 R:R minimum
        rr         = round((target - price) / stop_dist, 2)

        return {
            "symbol":        symbol,
            "price":         round(price, 2),
            "prev_close":    round(prev_close, 2),
            "open":          round(open_price, 2),
            "gap_pct":       round(gap_pct, 2),
            "avg_volume":    int(avg_volume),
            "vol_vs_avg":    round(vol_vs_avg, 2),
            "market_cap":    market_cap,
            "beta":          round(beta, 2),
            "rsi":           rsi,
            "macd_val":      round(macd_val, 4),
            "macd_sig":      round(macd_sig, 4),
            "macd_hist":     round(macd_hist, 4),
            "macd_bullish":  macd_bullish,
            "macd_crossover": macd_crossover,
            "sma20":         round(sma20, 2),
            "sma50":         round(sma50, 2),
            "vwap":          round(vwap, 2),
            "above_vwap":    above_vwap,
            "uptrend":       uptrend,
            "earnings_soon": earnings_soon,
            "stop":          stop,
            "target":        target,
            "stop_dist":     round(stop_dist, 2),
            "rr":            rr,
            "atr":           round(atr, 2),
        }
    except Exception as e:
        print(f"[DATA] {symbol}: {e}")
        return None
