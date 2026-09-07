#!/usr/bin/env python3
"""Offline tests for full_stack_smoke health probes (stdlib).

Run: python3 infra/scripts/ci/test_full_stack_smoke.py
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_CI = Path(__file__).resolve().parent
if str(_CI) not in sys.path:
    sys.path.insert(0, str(_CI))

from full_stack_smoke import probe_json_detail  # noqa: E402


class _JsonHandler(BaseHTTPRequestHandler):
    status_code = 200
    payload: dict = {"status": "ok"}

    def do_GET(self) -> None:
        raw = json.dumps(self.payload).encode()
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args) -> None:
        return


def _serve(status_code: int, payload: dict) -> HTTPServer:
    handler = type(
        "H",
        (_JsonHandler,),
        {"status_code": status_code, "payload": payload},
    )
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class ProbeJsonDetailTests(unittest.TestCase):
    def test_ok_when_status_ok(self) -> None:
        server = _serve(200, {"status": "ok"})
        try:
            ok, detail = probe_json_detail(f"http://127.0.0.1:{server.server_address[1]}/v1/health")
            self.assertTrue(ok)
            self.assertIn("status", detail)
        finally:
            server.shutdown()
            server.server_close()

    def test_false_when_clickhouse_unavailable(self) -> None:
        server = _serve(
            503,
            {"status": "unavailable", "analytics": {"clickhouse": False, "configured": True}},
        )
        try:
            ok, detail = probe_json_detail(f"http://127.0.0.1:{server.server_address[1]}/v1/health")
            self.assertFalse(ok)
            self.assertIn("503", detail)
            self.assertIn("clickhouse", detail)
        finally:
            server.shutdown()
            server.server_close()

    def test_false_when_nothing_listens(self) -> None:
        ok, detail = probe_json_detail("http://127.0.0.1:1/v1/health", timeout=0.3)
        self.assertFalse(ok)
        self.assertTrue(detail.startswith("error="))


if __name__ == "__main__":
    unittest.main()
