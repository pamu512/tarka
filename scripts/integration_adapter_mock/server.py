#!/usr/bin/env python3
from __future__ import annotations

"""
Minimal HTTP server stubbing Case API, Graph Service, and Decision API paths
used by investigation-agent tools (stdlib only).

  python scripts/integration_adapter_mock/server.py --port 18080
"""


import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


def _json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        n = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        n = 0
    if n <= 0:
        return {}
    raw = handler.rfile.read(n)
    try:
        return json.loads(raw.decode())
    except json.JSONDecodeError:
        return {}


class Handler(BaseHTTPRequestHandler):
    server_version = "SaarthiMock/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[mock] {self.address_string()} - {fmt % args}")

    def _send(self, code: int, obj: Any) -> None:
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self) -> None:  # noqa: N802
        p = urlparse(self.path)
        path = p.path

        if path == "/v1/cases":
            self._send(
                200,
                {
                    "items": [
                        {
                            "id": "00000000-0000-4000-8000-000000000001",
                            "status": "open",
                            "priority": "medium",
                            "entity_id": "entity_demo_1",
                            "trace_id": "12345678-1234-5678-9012-123456789abc",
                        }
                    ],
                    "tenant_id": parse_qs(p.query).get("tenant_id", ["demo"])[0],
                },
            )
            return

        m = re.match(r"^/v1/cases/([^/]+)$", path)
        if m:
            cid = m.group(1)
            # Body is the case object; agent wraps as {"case": r.json()}.
            self._send(
                200,
                {
                    "id": cid,
                    "status": "open",
                    "entity_id": "entity_demo_1",
                    "trace_id": "12345678-1234-5678-9012-123456789abc",
                },
            )
            return

        if path == "/v1/disputes":
            self._send(200, {"items": []})
            return

        if path == "/v1/investigation-label-drafts":
            self._send(200, {"items": []})
            return

        if path == "/v1/subgraph":
            self._send(
                200,
                {
                    "nodes": [{"id": "entity_demo_1", "properties": {"external_id": "entity_demo_1"}}],
                    "edges": [],
                },
            )
            return

        m = re.match(r"^/v1/entities/([^/]+)/tags$", path)
        if m:
            self._send(200, {"tags": [], "entity_id": m.group(1)})
            return

        if path == "/v1/analyst/entity-velocity":
            self._send(
                200,
                {
                    "entity_id": parse_qs(p.query).get("entity_id", [""])[0],
                    "event_count_5m": 0,
                    "event_count_1h": 0,
                    "event_count_24h": 0,
                },
            )
            return

        m = re.match(r"^/v1/audit/([^/]+)$", path)
        if m:
            tid = m.group(1)
            # Body is the audit row; agent wraps as {"audit": r.json()}.
            self._send(
                200,
                {
                    "trace_id": tid,
                    "decision": "review",
                    "inference_context": {},
                },
            )
            return

        self._send(404, {"error": "not_found", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        p = urlparse(self.path)
        path = p.path
        _ = _json_body(self)

        if path == "/v1/investigation-label-drafts/batch":
            self._send(200, {"ok": True, "stored": 0})
            return

        if path == "/v1/replay":
            self._send(
                200,
                {
                    "tenant_id": "demo",
                    "events_evaluated": 0,
                    "decisions_changed": 0,
                    "results": [],
                },
            )
            return

        self._send(404, {"error": "not_found", "path": path})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18080)
    args = ap.parse_args()
    httpd = HTTPServer((args.host, args.port), Handler)
    print(f"Saarthi upstream mock on http://{args.host}:{args.port} (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
