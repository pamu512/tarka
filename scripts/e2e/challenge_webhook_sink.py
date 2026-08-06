#!/usr/bin/env python3
"""Minimal challenge webhook sink for Micro/E2E (Track D).

POST any path → 200 JSON {ok:true}; append body to --log-file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--log-file", type=Path, default=Path("/tmp/challenge_webhook_sink.jsonl"))
    args = p.parse_args()
    log_path: Path = args.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *a) -> None:  # noqa: A003
            return

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b""
            entry = {
                "ts": datetime.now(UTC).isoformat(),
                "path": self.path,
                "headers": {
                    k: v
                    for k, v in self.headers.items()
                    if k.lower() in ("content-type", "x-tarka-signature", "x-tarka-challenge-event")
                },
                "body": raw.decode("utf-8", errors="replace"),
            }
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
            out = json.dumps({"ok": True, "schema_id": "tarka.challenge_webhook_sink/v1"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self) -> None:  # noqa: N802
            out = b'{"ok":true,"service":"challenge_webhook_sink"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"challenge_webhook_sink listening on {args.host}:{args.port} log={log_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
