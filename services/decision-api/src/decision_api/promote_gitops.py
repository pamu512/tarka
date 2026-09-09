"""Desk Promote is live SoT. Git export is backup — not the go-live gate.

Consumer contract: docs/contracts/pack-promote-export-v1.md
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("decision-api.promote_gitops")

SCHEMA_ID = "tarka.pack_promote_export/v1"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def emit_promote_export(
    *,
    pack_id: str,
    pack_hash: str,
    mode: str,
    actor: str,
    reason: str,
    file: str = "",
) -> dict[str, Any]:
    event = {
        "schema_id": SCHEMA_ID,
        "pack_id": pack_id,
        "pack_hash": pack_hash,
        "mode": mode,
        "actor": actor,
        "reason": reason,
        "file": file,
        "emitted_at": _now(),
    }
    dest = Path(
        os.environ.get("PACK_GITOPS_EXPORT_PATH")
        or Path(os.environ.get("RULES_PATH") or ".") / "_loop" / "promote_export.jsonl"
    )
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except OSError:
        log.debug("promote_export_write_failed", exc_info=True)
    return event
