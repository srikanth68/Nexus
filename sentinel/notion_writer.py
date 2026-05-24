import requests
from datetime import datetime
from config import NOTION_TOKEN, NOTION_SIGNALS_DB_ID, NOTION_PORTFOLIO_DB_ID

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

BASE = "https://api.notion.com/v1"


# ── helpers ────────────────────────────────────────────────────────────────

def _text(val: str):
    return {"rich_text": [{"text": {"content": str(val)}}]}

def _title(val: str):
    return {"title": [{"text": {"content": str(val)}}]}

def _number(val):
    return {"number": float(val) if val is not None else None}

def _select(val: str):
    return {"select": {"name": str(val)}}

def _date(val: str):
    return {"date": {"start": val}}


# ── database creation ───────────────────────────────────────────────────────

def _create_signals_db(parent_page_id: str) -> str:
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "Sentinel Signals"}}],
        "properties": {
            "Symbol":     {"title": {}},
            "Signal":     {"select": {"options": [
                {"name": "STRONG BUY", "color": "green"},
                {"name": "BUY",        "color": "blue"},
                {"name": "SELL",       "color": "red"},
                {"name": "HOLD",       "color": "yellow"},
            ]}},
            "Confidence": {"number": {"format": "number"}},
            "Entry":      {"number": {"format": "dollar"}},
            "Target":     {"number": {"format": "dollar"}},
            "Stop":       {"number": {"format": "dollar"}},
            "Strategy":   {"rich_text": {}},
            "Reasoning":  {"rich_text": {}},
            "Timestamp":  {"date": {}},
        },
    }
    r = requests.post(f"{BASE}/databases", headers=HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    db_id = r.json()["id"]
    print(f"[NOTION] Created 'Sentinel Signals' DB: {db_id}")
    return db_id


def _create_portfolio_db(parent_page_id: str) -> str:
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "Sentinel Portfolio"}}],
        "properties": {
            "Symbol":  {"title": {}},
            "Entry":   {"number": {"format": "dollar"}},
            "Stop":    {"number": {"format": "dollar"}},
            "Target":  {"number": {"format": "dollar"}},
            "Qty":     {"number": {"format": "number"}},
            "Date":    {"date": {}},
            "Status":  {"select": {"options": [
                {"name": "open",   "color": "green"},
                {"name": "closed", "color": "default"},
            ]}},
            "PnL%":    {"number": {"format": "percent"}},
        },
    }
    r = requests.post(f"{BASE}/databases", headers=HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    db_id = r.json()["id"]
    print(f"[NOTION] Created 'Sentinel Portfolio' DB: {db_id}")
    return db_id


def ensure_databases(parent_page_id: str = None):
    """Create both DBs if IDs not set. Returns (signals_id, portfolio_id)."""
    if NOTION_SIGNALS_DB_ID and NOTION_PORTFOLIO_DB_ID:
        return NOTION_SIGNALS_DB_ID, NOTION_PORTFOLIO_DB_ID
    if not parent_page_id:
        raise ValueError("Pass a parent_page_id to create databases automatically.")
    s = _create_signals_db(parent_page_id)
    p = _create_portfolio_db(parent_page_id)
    print(f"\nAdd these to your .env:\nNOTION_SIGNALS_DB_ID={s}\nNOTION_PORTFOLIO_DB_ID={p}\n")
    return s, p


# ── signals ─────────────────────────────────────────────────────────────────

def write_signal(signal: dict) -> str | None:
    """Write one signal row. Returns page_id or None on failure."""
    if not NOTION_SIGNALS_DB_ID:
        print("[NOTION] NOTION_SIGNALS_DB_ID not set — skipping write.")
        return None
    ts = signal.get("timestamp", datetime.utcnow().isoformat())
    payload = {
        "parent": {"database_id": NOTION_SIGNALS_DB_ID},
        "properties": {
            "Symbol":     _title(signal["symbol"]),
            "Signal":     _select(signal["signal"]),
            "Confidence": _number(signal.get("confidence", 0)),
            "Entry":      _number(signal.get("entry")),
            "Target":     _number(signal.get("target")),
            "Stop":       _number(signal.get("stop")),
            "Strategy":   _text(signal.get("strategy", "")),
            "Reasoning":  _text(signal.get("reasoning", "")),
            "Timestamp":  _date(ts[:10]),
        },
    }
    try:
        r = requests.post(f"{BASE}/pages", headers=HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        page_id = r.json()["id"]
        print(f"[NOTION] Signal written for {signal['symbol']} ({signal['signal']}) → {page_id}")
        return page_id
    except requests.RequestException as e:
        print(f"[NOTION] write_signal failed: {e}")
        return None


def write_signals_batch(signals: list[dict]):
    for s in signals:
        write_signal(s)


# ── portfolio ───────────────────────────────────────────────────────────────

def add_position(pos: dict) -> str | None:
    if not NOTION_PORTFOLIO_DB_ID:
        print("[NOTION] NOTION_PORTFOLIO_DB_ID not set — skipping.")
        return None
    payload = {
        "parent": {"database_id": NOTION_PORTFOLIO_DB_ID},
        "properties": {
            "Symbol": _title(pos["symbol"]),
            "Entry":  _number(pos.get("entry")),
            "Stop":   _number(pos.get("stop")),
            "Target": _number(pos.get("target")),
            "Qty":    _number(pos.get("qty", 0)),
            "Date":   _date(pos.get("date", datetime.utcnow().date().isoformat())),
            "Status": _select("open"),
            "PnL%":   _number(0),
        },
    }
    try:
        r = requests.post(f"{BASE}/pages", headers=HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()["id"]
    except requests.RequestException as e:
        print(f"[NOTION] add_position failed: {e}")
        return None


def get_open_positions() -> list[dict]:
    if not NOTION_PORTFOLIO_DB_ID:
        return []
    payload = {"filter": {"property": "Status", "select": {"equals": "open"}}}
    try:
        r = requests.post(
            f"{BASE}/databases/{NOTION_PORTFOLIO_DB_ID}/query",
            headers=HEADERS, json=payload, timeout=15,
        )
        r.raise_for_status()
        rows = r.json().get("results", [])
        positions = []
        for row in rows:
            p = row["properties"]
            def num(key):
                n = p.get(key, {}).get("number")
                return float(n) if n is not None else None
            def txt(key):
                arr = p.get(key, {}).get("title") or p.get(key, {}).get("rich_text") or []
                return arr[0]["text"]["content"] if arr else ""
            positions.append({
                "page_id": row["id"],
                "symbol":  txt("Symbol"),
                "entry":   num("Entry"),
                "stop":    num("Stop"),
                "target":  num("Target"),
                "qty":     num("Qty"),
                "pnl_pct": num("PnL%"),
            })
        return positions
    except requests.RequestException as e:
        print(f"[NOTION] get_open_positions failed: {e}")
        return []


def update_position(page_id: str, pnl_pct: float = None,
                    status: str = None, current_price: float = None):
    props = {}
    if pnl_pct is not None:
        props["PnL%"] = _number(pnl_pct)
    if status:
        props["Status"] = _select(status)
    if not props:
        return
    try:
        r = requests.patch(
            f"{BASE}/pages/{page_id}",
            headers=HEADERS, json={"properties": props}, timeout=15,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[NOTION] update_position failed: {e}")


def get_all_signals_today() -> list[dict]:
    """Fetch today's signals for the dashboard."""
    if not NOTION_SIGNALS_DB_ID:
        return []
    today = datetime.utcnow().date().isoformat()
    payload = {
        "filter": {
            "property": "Timestamp",
            "date": {"equals": today},
        },
        "sorts": [{"property": "Confidence", "direction": "descending"}],
    }
    try:
        r = requests.post(
            f"{BASE}/databases/{NOTION_SIGNALS_DB_ID}/query",
            headers=HEADERS, json=payload, timeout=15,
        )
        r.raise_for_status()
        rows = r.json().get("results", [])
        signals = []
        for row in rows:
            p = row["properties"]
            def num(key):
                n = p.get(key, {}).get("number")
                return float(n) if n is not None else None
            def sel(key):
                s = p.get(key, {}).get("select")
                return s["name"] if s else ""
            def txt(key):
                arr = p.get(key, {}).get("title") or p.get(key, {}).get("rich_text") or []
                return arr[0]["text"]["content"] if arr else ""
            signals.append({
                "symbol":     txt("Symbol"),
                "signal":     sel("Signal"),
                "confidence": num("Confidence"),
                "entry":      num("Entry"),
                "target":     num("Target"),
                "stop":       num("Stop"),
                "strategy":   txt("Strategy"),
                "reasoning":  txt("Reasoning"),
            })
        return signals
    except requests.RequestException as e:
        print(f"[NOTION] get_all_signals_today failed: {e}")
        return []


if __name__ == "__main__":
    test_signal = {
        "symbol": "TEST",
        "signal": "BUY",
        "confidence": 85,
        "entry": 100.00,
        "target": 106.00,
        "stop": 97.00,
        "strategy": "RSI+MACD",
        "reasoning": "RSI oversold + MACD bullish cross on high volume",
        "timestamp": datetime.utcnow().date().isoformat(),
    }
    page_id = write_signal(test_signal)
    if page_id:
        print(f"[NOTION] Test write succeeded: {page_id}")
    else:
        print("[NOTION] Test write failed — check NOTION_TOKEN and NOTION_SIGNALS_DB_ID in .env")
