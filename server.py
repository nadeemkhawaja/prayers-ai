#!/usr/bin/env python3
"""
Prayers AI — single-process server.

Serves the PWA (index.html, data.json, manifest, icons) and exposes:
    GET  /health      -> scrape status
    POST /api/refresh -> queue an immediate scrape

A background thread runs scrape.main() at startup and every
SCRAPE_INTERVAL_HOURS (default 12).
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("REPO_PATH", str(ROOT))
sys.path.insert(0, str(ROOT / "scraper"))

import scrape  # noqa: E402

PORT = int(os.environ.get("PORT", "8080"))
INTERVAL_H = float(os.environ.get("SCRAPE_INTERVAL_HOURS", "12"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prayers-ai")

_state = {"last_run": None, "last_status": "pending", "running": False}
_lock = threading.Lock()


def run_scrape():
    with _lock:
        if _state["running"]:
            return
        _state["running"] = True
    try:
        log.info("Scrape starting")
        scrape.main()
        _state["last_status"] = "ok"
        log.info("Scrape done")
    except Exception as e:
        log.exception("Scrape failed")
        _state["last_status"] = f"error: {e}"
    finally:
        _state["last_run"] = datetime.now(timezone.utc).isoformat()
        _state["running"] = False


def scheduler():
    while True:
        run_scrape()
        time.sleep(INTERVAL_H * 3600)


class Handler(SimpleHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        if self.path.endswith("data.json") or self.path == "/data.json":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"status": "ok", **_state})
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/refresh":
            threading.Thread(target=run_scrape, daemon=True).start()
            return self._json(202, {"status": "queued"})
        return self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


def main():
    threading.Thread(target=scheduler, daemon=True).start()
    log.info("Prayers AI on 0.0.0.0:%d (scrape every %sh)", PORT, INTERVAL_H)
    ThreadingHTTPServer(("0.0.0.0", PORT), partial(Handler, directory=str(ROOT))).serve_forever()


if __name__ == "__main__":
    main()
