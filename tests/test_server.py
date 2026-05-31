"""
Tests for the HTTP server endpoints.
A real ThreadingHTTPServer is started on a random port; scrape.main is
patched so tests never touch the network or filesystem outside tmp_path.
"""
import http.client
import json
import sys
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import server


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("srv")
    (tmp / "data.json").write_text(json.dumps({"mosques": []}))
    (tmp / "index.html").write_text("<html><body>OK</body></html>")

    with patch("server.scrape.main", return_value=None):
        server._state.update({"last_run": None, "last_status": "pending", "running": False})
        handler = partial(server.Handler, directory=str(tmp))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        yield httpd.server_address
        httpd.shutdown()


def _get(addr, path):
    conn = http.client.HTTPConnection(*addr)
    conn.request("GET", path)
    return conn.getresponse()


def _post(addr, path):
    conn = http.client.HTTPConnection(*addr)
    conn.request("POST", path)
    return conn.getresponse()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_200(self, live_server):
        resp = _get(live_server, "/health")
        assert resp.status == 200

    def test_content_type_is_json(self, live_server):
        resp = _get(live_server, "/health")
        assert "application/json" in resp.getheader("Content-Type", "")

    def test_body_contains_status_ok(self, live_server):
        resp = _get(live_server, "/health")
        data = json.loads(resp.read())
        assert data["status"] == "ok"

    def test_body_contains_state_fields(self, live_server):
        resp = _get(live_server, "/health")
        data = json.loads(resp.read())
        assert "last_run" in data
        assert "last_status" in data
        assert "running" in data

    def test_cache_control_no_store(self, live_server):
        resp = _get(live_server, "/health")
        resp.read()
        assert resp.getheader("Cache-Control") == "no-store"


# ---------------------------------------------------------------------------
# POST /api/refresh
# ---------------------------------------------------------------------------

class TestRefreshEndpoint:
    def test_returns_202(self, live_server):
        with patch("server.scrape.main", return_value=None):
            resp = _post(live_server, "/api/refresh")
        assert resp.status == 202

    def test_body_contains_queued_status(self, live_server):
        with patch("server.scrape.main", return_value=None):
            resp = _post(live_server, "/api/refresh")
            data = json.loads(resp.read())
        assert data["status"] == "queued"

    def test_content_type_is_json(self, live_server):
        with patch("server.scrape.main", return_value=None):
            resp = _post(live_server, "/api/refresh")
            resp.read()
        assert "application/json" in resp.getheader("Content-Type", "")


# ---------------------------------------------------------------------------
# POST unknown path
# ---------------------------------------------------------------------------

class TestUnknownPost:
    def test_returns_404(self, live_server):
        resp = _post(live_server, "/nonexistent")
        assert resp.status == 404

    def test_body_contains_error(self, live_server):
        resp = _post(live_server, "/nonexistent")
        data = json.loads(resp.read())
        assert "error" in data


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

class TestStaticFiles:
    def test_serves_index_html(self, live_server):
        resp = _get(live_server, "/index.html")
        assert resp.status == 200

    def test_data_json_has_no_store_header(self, live_server):
        resp = _get(live_server, "/data.json")
        resp.read()
        assert resp.getheader("Cache-Control") == "no-store"


# ---------------------------------------------------------------------------
# run_scrape mutex
# ---------------------------------------------------------------------------

class TestRunScrapeMutex:
    def test_concurrent_calls_do_not_double_execute(self):
        import time
        call_count = {"n": 0}
        t1_started = threading.Event()

        def slow_main():
            call_count["n"] += 1
            t1_started.set()
            time.sleep(0.2)  # hold _state["running"]=True so t2 sees it

        server._state["running"] = False
        with patch("server.scrape.main", side_effect=slow_main):
            t1 = threading.Thread(target=server.run_scrape)
            t1.start()
            t1_started.wait(timeout=2)  # t2 starts only after t1 is inside scrape.main

            t2 = threading.Thread(target=server.run_scrape)
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        assert call_count["n"] == 1
