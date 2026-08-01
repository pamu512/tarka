#!/usr/bin/env python3
"""Minimal mock receiver for tarka.enforcement/v1 (+ challenge) webhooks.

Usage::

  python3 scripts/oss/enforcement_webhook_mock.py --port 8765

POSTs land on /enforcement and /challenge. Prints JSON bodies; optional HMAC check
when TARKA_ENFORCEMENT_WEBHOOK_SECRET / TARKA_CHALLENGE_WEBHOOK_SECRET is set.

See docs/docs/guides/decide-to-act-enforcement.md
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _verify(raw: bytes, secret: str, header_sig: str | None) -> bool:
    if not secret:
        return True
    if not header_sig:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig.strip())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quieter default
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = self.path.split("?", 1)[0]
        sig = self.headers.get("x-tarka-signature")
        if path.endswith("/challenge") or path == "/challenge":
            secret = os.environ.get("TARKA_CHALLENGE_WEBHOOK_SECRET", "").strip()
            event = self.headers.get("x-tarka-challenge-event", "")
            kind = "challenge"
        else:
            secret = os.environ.get("TARKA_ENFORCEMENT_WEBHOOK_SECRET", "").strip()
            event = self.headers.get("x-tarka-enforcement-event", "")
            kind = "enforcement"

        if not _verify(raw, secret, sig):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"bad_signature"}')
            print(f"[reject] {kind} bad signature event={event}", file=sys.stderr)
            return

        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {"_raw": raw.decode("utf-8", errors="replace")}

        print(f"[ok] {kind} event={event} path={path}")
        print(json.dumps(body, indent=2, sort_keys=True))
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] in ("/health", "/"):
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"enforcement-webhook-mock"}')
            return
        self.send_response(404)
        self.end_headers()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"listening http://{args.host}:{args.port}/enforcement "
        f"(and /challenge) — Ctrl+C to stop",
        file=sys.stderr,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
