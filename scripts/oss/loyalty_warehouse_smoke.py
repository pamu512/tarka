#!/usr/bin/env python3
"""Track C: mock HTTP warehouse — complete gates; incomplete never eligible:true."""

from __future__ import annotations

import json
import os
import sys
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(_REPO / "services" / "decision-api" / "src"))

from decision_api.loyalty_economics import evaluate_loyalty_economics  # noqa: E402
from decision_api.loyalty_warehouse import (  # noqa: E402
    fetch_loyalty_warehouse_pack,
    validate_loyalty_warehouse_pack,
)


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, Path] = {}

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        target = self.routes.get(path)
        if target is None or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _any_eligible_true(gates: dict) -> bool:
    for g in (gates.get("gates") or {}).values():
        if isinstance(g, dict) and g.get("eligible") is True:
            return True
    return False


def main() -> int:
    complete = _FIX / "loyalty_warehouse_complete.json"
    incomplete = _FIX / "loyalty_warehouse_incomplete.json"
    handler = type(
        "H",
        (_Handler,),
        {"routes": {"/complete": complete, "/incomplete": incomplete}},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    errors: list[str] = []
    try:
        pack = fetch_loyalty_warehouse_pack(f"{base}/complete")
        if pack["gates_preview"]["order_eligible"] is not True:
            errors.append("complete pack should have order eligible true")
        if pack["gates_preview"]["order_decision_untouched"] is not True:
            errors.append("order_decision_untouched missing")

        raw_inc = json.loads(incomplete.read_text(encoding="utf-8"))
        validated = validate_loyalty_warehouse_pack(raw_inc)
        gates = evaluate_loyalty_economics(
            entity_id=validated["entity_id"],
            feed_snapshot=validated["loyalty_feed_snapshot"],
            program_config=validated["loyalty_program_config"],
        )
        if gates.get("status") != "feeds_incomplete":
            errors.append(f"incomplete status={gates.get('status')}")
        if _any_eligible_true(gates):
            errors.append("incomplete must never set eligible:true")
    finally:
        server.shutdown()

    report = {
        "ok": not errors,
        "schema_id": "tarka.loyalty_warehouse_smoke/v1",
        "errors": errors,
    }
    print(json.dumps(report, indent=2))
    art = os.environ.get("LOYALTY_WAREHOUSE_ARTIFACT", "").strip()
    if art:
        path = Path(art)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
