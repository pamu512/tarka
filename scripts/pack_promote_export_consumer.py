"""Sample backup sink for tarka.pack_promote_export/v1.

Desk Promote is live SoT. This script writes a commit-message stub from the
export JSONL. It does not Promote, demote, or gate go-live.

Empty PACK_PROMOTE_EXPORT_CONSUMER_URL = outbound notify off.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable

SCHEMA_ID = "tarka.pack_promote_export/v1"
NOTIFY_URL_ENV = "PACK_PROMOTE_EXPORT_CONSUMER_URL"
REQUIRED_FIELDS = (
    "schema_id",
    "pack_id",
    "pack_hash",
    "mode",
    "actor",
    "reason",
    "file",
    "emitted_at",
)

NotifyFn = Callable[[str, dict[str, Any], Path], None]


class ConsumeError(Exception):
    def __init__(self, code: str, message: str, *, line: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.line = line

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": False,
            "error": self.code,
            "message": self.message,
        }
        if self.line is not None:
            out["line"] = self.line
        return out


def idempotency_key(event: dict[str, Any]) -> tuple[str, str, str]:
    return (str(event["pack_id"]), str(event["pack_hash"]), str(event["emitted_at"]))


def parse_event(raw: dict[str, Any] | str | bytes) -> dict[str, Any]:
    if isinstance(raw, (str, bytes)):
        try:
            obj: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConsumeError("malformed", f"invalid json: {exc}") from exc
    elif isinstance(raw, dict):
        obj = raw
    else:
        raise ConsumeError("malformed", "event must be an object or json line")
    if not isinstance(obj, dict):
        raise ConsumeError("malformed", "event must be an object")
    if obj.get("schema_id") != SCHEMA_ID:
        raise ConsumeError(
            "malformed",
            "schema_id must be tarka.pack_promote_export/v1",
        )
    missing = [name for name in REQUIRED_FIELDS if name not in obj]
    if missing:
        raise ConsumeError("malformed", f"missing fields: {missing}")
    return obj


def artifact_path(dest_dir: Path, event: dict[str, Any]) -> Path:
    pack_id, pack_hash, emitted_at = idempotency_key(event)
    digest = hashlib.sha256(f"{pack_id}|{pack_hash}|{emitted_at}".encode()).hexdigest()[
        :20
    ]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", pack_id)[:64] or "pack"
    return dest_dir / f"{safe}__{digest}.commit.txt"


def render_commit_stub(event: dict[str, Any]) -> str:
    return (
        f"Promote pack {event['pack_id']} ({event['pack_hash']})\n"
        "\n"
        f"schema_id: {event['schema_id']}\n"
        f"emitted_at: {event['emitted_at']}\n"
        f"mode: {event['mode']}\n"
        f"actor: {event['actor']}\n"
        f"reason: {event['reason']}\n"
        f"file: {event['file']}\n"
        "\n"
        "Desk Promote is the live source of truth. This stub is a git backup "
        "of the export event, not go-live authority.\n"
    )


def _default_notify(url: str, event: dict[str, Any], path: Path) -> None:
    body = json.dumps({"artifact": str(path), "event": event}, sort_keys=True).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def consume_event(
    raw: dict[str, Any] | str | bytes,
    dest_dir: Path | str,
    *,
    notify_url: str | None = None,
    notify: NotifyFn | None = None,
) -> dict[str, Any]:
    event = parse_event(raw)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = artifact_path(dest, event)
    key = idempotency_key(event)
    if path.exists():
        return {
            "ok": True,
            "artifact": str(path),
            "idempotent": True,
            "idempotency_key": key,
        }
    path.write_text(render_commit_stub(event), encoding="utf-8")
    url = (
        notify_url
        if notify_url is not None
        else os.environ.get(NOTIFY_URL_ENV, "")
    )
    if (url or "").strip():
        sender = notify if notify is not None else _default_notify
        sender(url, event, path)
    return {
        "ok": True,
        "artifact": str(path),
        "idempotent": False,
        "idempotency_key": key,
    }


def consume_after_emit(
    event: dict[str, Any] | str | bytes,
    dest_dir: Path | str,
    *,
    notify_url: str = "",
    notify: NotifyFn | None = None,
) -> dict[str, Any]:
    """Optional follow-on after emit. Empty URL = plane off. Never raises."""
    if not (notify_url or "").strip():
        return {"ok": True, "skipped": True, "reason": "empty_url"}
    try:
        return consume_event(event, dest_dir, notify_url=notify_url, notify=notify)
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }


def consume_jsonl(
    path: Path | str,
    dest_dir: Path | str,
    *,
    notify_url: str | None = None,
    notify: NotifyFn | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            results.append(
                consume_event(line, dest_dir, notify_url=notify_url, notify=notify)
            )
        except ConsumeError as exc:
            if exc.line is None:
                exc.line = i
            results.append(exc.as_dict())
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read tarka.pack_promote_export/v1 JSONL and write commit-message "
            "backup stubs. Does not gate desk Promote."
        )
    )
    parser.add_argument("--input", required=True, help="Export JSONL path")
    parser.add_argument("--out-dir", required=True, help="Directory for .commit.txt stubs")
    parser.add_argument(
        "--notify-url",
        default="",
        help="Optional outbound URL. Empty = off (default).",
    )
    args = parser.parse_args(argv)
    url = (args.notify_url or os.environ.get(NOTIFY_URL_ENV, "")).strip()
    rows = consume_jsonl(args.input, args.out_dir, notify_url=url or "")
    json.dump(rows, sys.stdout)
    sys.stdout.write("\n")
    return 0 if all(row.get("ok") for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
