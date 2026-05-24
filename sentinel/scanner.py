"""
scanner.py — deep scan engine for Sentinel Lite
Primary data: TradingView MCP  |  Fallback: yfinance
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from config import (
    CORE_WATCHLIST, RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_NEUTRAL,
    VOLUME_SPIKE_MULTIPLIER, DEFAULT_STOP_PCT, DEFAULT_TARGET_PCT,
    MIN_RISK_REWARD, PREMARKET_MIN_VOLUME, PREMARKET_MIN_CHANGE_PCT,
)


# ── technical indicators (pure pandas, no TA-Lib needed) ────────────────────

def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def _macd(series: pd.Series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(hist.iloc[-1])


def _sma(series: pd.Series, period: int) -> float:
    return round(float(series.rolling(period).mean().iloc[-1]), 4)


def _volume_spike(vol_series: pd.Series, period: int = 20) -> bool:
    avg_vol = vol_series.iloc[-period-1:-1].mean()
    current_vol = vol_series.iloc[-1]
    return bool(current_vol > avg_vol * VOLUME_SPIKE_MULTIPLIER)


# ── data fetching ────────────────────────────────────────────────────────────

def _fetch_yfinance(symbol: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame | None:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        print(f"[SCANNER] yfinance fetch failed for {symbol}: {e}")
        return None


def _get_indicators(symbol: str, mcp_data: dict | None = None) -> dict | None:
    """
    Try to build indicator dict from MCP data first, fall back to yfinance.
    mcp_data shape (if provided by TradingView MCP):
      { "close": [...], "volume": [...], "rsi": float, "macd": {...}, ... }
    """
    # ── Path 1: TradingView MCP supplied data ─────────────────────────
    if mcp_data and "close" in mcp_data:
        closes = pd.Series(mcp_data["close"])
        vols   = pd.Series(mcp_data.get("volume", []))
        rsi    = mcp_data.get("rsi") or _rsi(closes)
        if "macd" in mcp_data:
            m = mcp_data["macd"]
            macd_val, macd_sig, macd_hist = m["macd"], m["signal"], m["histogram"]
        else:
            macd_val, macd_sig, macd_hist = _macd(closes)
        sma20 = mcp_data.get("sma20") or _sma(closes, 20)
        sma50 = mcp_data.get("sma50") or _sma(closes, 50)
        price = float(closes.iloc[-1])
        vol_spike = _volume_spike(vols) if len(vols) > 20 else False
    # ── Path 2: yfinance fallback ─────────────────────────────────────
    else:
        df = _fetch_yfinance(symbol)
        if df is None or len(df) < 30:
            print(f"[SCANNER] Insufficient data for {symbol}")
            return None
        closes = df["Close"]
        vols   = df["Volume"]
        rsi    = _rsi(closes)
        macd_val, macd_sig, macd_hist = _macd(closes)
        sma20  = _sma(closes, 20)
        sma50  = _sma(closes, 50)
        price  = float(closes.iloc[-1])
        vol_spike = _volume_spike(vols)

    return {
        "price":     round(price, 4),
        "rsi":       rsi,
        "macd":      macd_val,
        "macd_sig":  macd_sig,
        "macd_hist": macd_hist,
        "sma20":     sma20,
        "sma50":     sma50,
        "vol_spike": vol_spike,
    }


# ── signal logic ─────────────────────────────────────────────────────────────

def _classify_signal(ind: dict) -> tuple[str, int, str]:
    """Returns (signal, confidence, reasoning)."""
    rsi       = ind["rsi"]
    macd_hist = ind["macd_hist"]
    macd_val  = ind["macd"]
    macd_sig  = ind["macd_sig"]
    price     = ind["price"]
    sma20     = ind["sma20"]
    sma50     = ind["sma50"]
    vol_spike = ind["vol_spike"]

    macd_bullish_cross = macd_hist > 0 and macd_val > macd_sig
    macd_bearish_cross = macd_hist < 0 and macd_val < macd_sig
    macd_rising        = macd_hist > 0

    score   = 0
    reasons = []

    # ── STRONG BUY conditions ──────────────────────────────────────────
    if rsi < RSI_OVERSOLD:
        score += 25; reasons.append(f"RSI oversold ({rsi:.0f})")
    if macd_bullish_cross:
        score += 25; reasons.append("MACD bullish cross")
    if price > sma50:
        score += 20; reasons.append("price > SMA50")
    if vol_spike:
        score += 15; reasons.append("volume spike")

    if score >= 65 and rsi < RSI_OVERSOLD and macd_bullish_cross:
        signal = "STRONG BUY"
        confidence = min(score + 10, 100)
        return signal, confidence, " + ".join(reasons)

    # ── BUY conditions ─────────────────────────────────────────────────
    score2 = 0
    reasons2 = []
    if rsi < RSI_NEUTRAL:
        score2 += 20; reasons2.append(f"RSI neutral-low ({rsi:.0f})")
    if macd_rising:
        score2 += 20; reasons2.append("MACD rising")
    if price > sma20:
        score2 += 15; reasons2.append("price > SMA20")
    if vol_spike:
        score2 += 10; reasons2.append("volume spike")

    if score2 >= 35:
        return "BUY", min(score2 + 5, 90), " + ".join(reasons2)

    # ── SELL conditions ────────────────────────────────────────────────
    if rsi > RSI_OVERBOUGHT and macd_bearish_cross:
        sell_score = 70
        reasons3 = [f"RSI overbought ({rsi:.0f})", "MACD bearish cross"]
        if price < sma20:
            sell_score += 10; reasons3.append("price < SMA20")
        return "SELL", min(sell_score, 95), " + ".join(reasons3)

    return "HOLD", 30, f"No clear edge — RSI {rsi:.0f}, MACD {'pos' if macd_hist > 0 else 'neg'}"


def _calc_levels(price: float, signal: str) -> tuple[float, float, float, float]:
    """Returns (entry, stop, target, rr)."""
    entry = price
    if signal in ("STRONG BUY", "BUY"):
        stop   = round(entry * (1 - DEFAULT_STOP_PCT), 2)
        target = round(entry * (1 + DEFAULT_TARGET_PCT), 2)
    elif signal == "SELL":
        stop   = round(entry * (1 + DEFAULT_STOP_PCT), 2)
        target = round(entry * (1 - DEFAULT_TARGET_PCT), 2)
    else:
        stop   = round(entry * (1 - DEFAULT_STOP_PCT), 2)
        target = round(entry * (1 + DEFAULT_TARGET_PCT), 2)

    risk   = abs(entry - stop)
    reward = abs(target - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0
    return entry, stop, target, rr


# ── pre-market movers ─────────────────────────────────────────────────────────

def get_premarket_movers() -> list[str]:
    """
    Uses yfinance to find high-volume tech/momentum movers not in core list.
    Scans a broader universe and returns symbols with big pre-market moves.
    """
    candidates = [
        "SOFI", "PLTR", "MARA", "RIOT", "COIN", "HOOD", "RIVN", "LCID",
        "NIO", "BABA", "SNAP", "UBER", "LYFT", "RBLX", "SHOP", "SQ",
        "ROKU", "NFLX", "ORCL", "CRM", "INTC", "MU", "QCOM", "AVGO",
    ]
    movers = []
    for sym in candidates:
        if sym in CORE_WATCHLIST:
            continue
        try:
            t = yf.Ticker(sym)
            info = t.fast_info
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
            pre_price  = info.get("preMarketPrice") or info.get("regularMarketPrice")
            pre_vol    = info.get("regularMarketVolume", 0)
            if not prev_close or not pre_price:
                continue
            chg_pct = abs((pre_price - prev_close) / prev_close * 100)
            if chg_pct >= PREMARKET_MIN_CHANGE_PCT and pre_vol >= PREMARKET_MIN_VOLUME:
                movers.append(sym)
                print(f"[SCANNER] Pre-market mover: {sym} {chg_pct:+.1f}% vol={pre_vol:,}")
        except Exception:
            pass
    return movers[:5]  # cap at 5 extras


# ── main scan ─────────────────────────────────────────────────────────────────

def scan_symbol(symbol: str, mcp_data: dict | None = None) -> dict | None:
    """Full deep scan for one symbol. Returns signal dict or None."""
    print(f"[SCANNER] Scanning {symbol}...")
    ind = _get_indicators(symbol, mcp_data)
    if ind is None:
        return None

    signal, confidence, reasoning = _classify_signal(ind)
    entry, stop, target, rr = _calc_levels(ind["price"], signal)

    return {
        "symbol":     symbol,
        "signal":     signal,
        "confidence": confidence,
        "price":      ind["price"],
        "entry":      entry,
        "stop":       stop,
        "target":     target,
        "rr":         rr,
        "reasoning":  reasoning,
        "strategy":   "RSI+MACD+SMA+Volume",
        "timestamp":  datetime.utcnow().date().isoformat(),
        "indicators": ind,
    }


def run_full_scan(extra_symbols: list[str] | None = None,
                  mcp_fetcher=None) -> list[dict]:
    """
    Scan the full watchlist + optional extras.
    mcp_fetcher: callable(symbol) -> dict|None  (supply from run_scan.py)
    """
    symbols = list(CORE_WATCHLIST)
    if extra_symbols:
        symbols += [s for s in extra_symbols if s not in symbols]

    results = []
    for sym in symbols:
        mcp_data = mcp_fetcher(sym) if mcp_fetcher else None
        result = scan_symbol(sym, mcp_data)
        if result:
            results.append(result)

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results


if __name__ == "__main__":
    print("=== Sentinel Scanner — Single Symbol Test ===")
    result = scan_symbol("NVDA")
    if result:
        print(f"\nSymbol    : {result['symbol']}")
        print(f"Signal    : {result['signal']}")
        print(f"Confidence: {result['confidence']}/100")
        print(f"Price     : ${result['price']:.2f}")
        print(f"Entry     : ${result['entry']:.2f}")
        print(f"Target    : ${result['target']:.2f}")
        print(f"Stop      : ${result['stop']:.2f}")
        print(f"R:R       : 1:{result['rr']}")
        print(f"Reasoning : {result['reasoning']}")
    else:
        print("Scan returned no result.")
