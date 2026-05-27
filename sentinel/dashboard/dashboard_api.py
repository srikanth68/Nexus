"""
dashboard_api.py — local API + static file server for the NEXUS dashboard.

Run:  python dashboard/dashboard_api.py
Open: http://localhost:5050
"""

import sys, os, json
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests as _req
from config import NOTION_TOKEN, NOTION_SIGNALS_DB_ID, NOTION_PORTFOLIO_DB_ID

PORT    = 5050
HTML    = os.path.join(os.path.dirname(__file__), "index.html")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type":   "application/json",
}
BASE = "https://api.notion.com/v1"


# ── Notion helpers ────────────────────────────────────────────────────────────

def _num(props, key):
    v = props.get(key, {}).get("number")
    return float(v) if v is not None else None

def _sel(props, key):
    s = props.get(key, {}).get("select")
    return s["name"] if s else ""

def _txt(props, key):
    arr = (props.get(key, {}).get("title")
           or props.get(key, {}).get("rich_text") or [])
    return arr[0]["text"]["content"] if arr else ""

def _date_start(props, key):
    d = props.get(key, {}).get("date")
    return d["start"] if d else ""


def fetch_signals_today() -> list[dict]:
    if not NOTION_SIGNALS_DB_ID:
        return []
    today = datetime.now(timezone.utc).date().isoformat()
    payload = {
        "filter": {"property": "Timestamp", "date": {"equals": today}},
        "sorts":  [{"property": "Confidence", "direction": "descending"}],
        "page_size": 50,
    }
    try:
        r = _req.post(f"{BASE}/databases/{NOTION_SIGNALS_DB_ID}/query",
                      headers=HEADERS, json=payload, timeout=10)
        r.raise_for_status()
        out = []
        for row in r.json().get("results", []):
            p = row["properties"]
            out.append({
                "symbol":     _txt(p, "Symbol"),
                "signal":     _sel(p, "Signal"),
                "confidence": _num(p, "Confidence"),
                "entry":      _num(p, "Entry"),
                "target":     _num(p, "Target"),
                "stop":       _num(p, "Stop"),
                "strategy":   _txt(p, "Strategy"),
                "reasoning":  _txt(p, "Reasoning"),
            })
        return out
    except Exception as e:
        print(f"[API] signals fetch error: {e}")
        return []


def fetch_portfolio() -> list[dict]:
    if not NOTION_PORTFOLIO_DB_ID:
        return []
    payload = {
        "sorts": [{"property": "Date", "direction": "descending"}],
        "page_size": 50,
    }
    try:
        r = _req.post(f"{BASE}/databases/{NOTION_PORTFOLIO_DB_ID}/query",
                      headers=HEADERS, json=payload, timeout=10)
        r.raise_for_status()
        out = []
        for row in r.json().get("results", []):
            p = row["properties"]
            out.append({
                "page_id": row["id"],
                "symbol":  _txt(p, "Symbol"),
                "entry":   _num(p, "Entry"),
                "stop":    _num(p, "Stop"),
                "target":  _num(p, "Target"),
                "qty":     _num(p, "Qty"),
                "pnl_pct": _num(p, "PnL%"),
                "status":  _sel(p, "Status"),
                "date":    _date_start(p, "Date"),
            })
        return out
    except Exception as e:
        print(f"[API] portfolio fetch error: {e}")
        return []


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet server

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        with open(HTML, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path in ("/", "/dashboard"):
            self._html()

        elif path == "/signals":
            signals = fetch_signals_today()
            self._json({"signals": signals, "count": len(signals),
                        "date": datetime.now(timezone.utc).date().isoformat()})

        elif path == "/portfolio":
            positions = fetch_portfolio()
            open_pos  = [p for p in positions if p.get("status") == "open"]
            avg_pnl   = (sum(p["pnl_pct"] or 0 for p in open_pos) / len(open_pos)
                         if open_pos else 0)
            self._json({
                "positions":  positions,
                "open_count": len(open_pos),
                "avg_pnl":    round(avg_pnl, 2),
            })

        elif path == "/health":
            self._json({"status": "ok", "ts": datetime.utcnow().isoformat()})

        else:
            self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    if not NOTION_TOKEN:
        print("[API] WARNING: NOTION_TOKEN not set in .env — data will be empty.")
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"""
╔══════════════════════════════════════════╗
║   ⚡ NEXUS Dashboard API — running        ║
║   http://localhost:{PORT}                   ║
║   Ctrl+C to stop                          ║
╚══════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[API] Stopped.")
