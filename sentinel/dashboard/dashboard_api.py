"""
dashboard_api.py — tiny local HTTP API that serves Notion data to the dashboard.
Run once: python dashboard/dashboard_api.py
Then open dashboard/index.html in a browser.
"""

import sys
import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# allow imports from parent sentinel/ dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notion_writer import get_all_signals_today, get_open_positions

PORT = 5050


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[API] {self.address_string()} {fmt % args}")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "/signals":
            signals = get_all_signals_today()
            self._send_json({"signals": signals, "count": len(signals)})

        elif path == "/portfolio":
            positions = get_open_positions()
            total_pnl = sum(p.get("pnl_pct") or 0 for p in positions)
            self._send_json({
                "positions":   positions,
                "open_count":  len(positions),
                "total_pnl":   round(total_pnl, 2),
            })

        elif path == "/health":
            self._send_json({"status": "ok"})

        else:
            self._send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[API] Sentinel dashboard API running at http://127.0.0.1:{PORT}")
    print(f"[API] Open sentinel/dashboard/index.html in your browser")
    print(f"[API] Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[API] Stopped.")
