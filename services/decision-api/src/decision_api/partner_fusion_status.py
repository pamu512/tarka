"""Read machine-readable L2 partner fusion LIVE|WAIVED status (P0-L2)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_WAIVED_RE = re.compile(r"^WAIVED\s*[—\-]\s*reason:\s*(.+)$", re.IGNORECASE)


def parse_live_status_line(text: str) -> dict[str, Any]:
    line = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
    if not line:
        return {
            "status": "MISSING",
            "reason": "partner-fusion-proof.live.status missing or empty",
            "promote_live_claim_allowed": False,
        }
    if line.upper() == "LIVE":
        return {
            "status": "LIVE",
            "reason": "",
            "promote_live_claim_allowed": True,
        }
    m = _WAIVED_RE.match(line)
    if m:
        return {
            "status": "WAIVED",
            "reason": m.group(1).strip(),
            "promote_live_claim_allowed": False,
        }
    return {
        "status": "INVALID",
        "reason": f"unrecognized status line: {line[:120]}",
        "promote_live_claim_allowed": False,
    }


def load_partner_fusion_status(
    *,
    repo_root: Path | None = None,
    status_path: Path | None = None,
    live_sha_path: Path | None = None,
) -> dict[str, Any]:
    root = repo_root or Path(__file__).resolve().parents[4]
    status_file = status_path or (
        root / "docs" / "compliance" / "partner-fusion-proof.live.status"
    )
    sha_file = live_sha_path or (
        root / "docs" / "compliance" / "partner-fusion-proof.live.sha256"
    )
    if status_file.is_file():
        parsed = parse_live_status_line(status_file.read_text(encoding="utf-8"))
    else:
        parsed = parse_live_status_line("")
    live_sha = ""
    if sha_file.is_file():
        live_sha = sha_file.read_text(encoding="utf-8").strip()
    if parsed["status"] == "LIVE" and not live_sha:
        parsed = {
            **parsed,
            "status": "INVALID",
            "reason": "LIVE requires non-empty partner-fusion-proof.live.sha256",
            "promote_live_claim_allowed": False,
        }
    return {
        "schema_id": "tarka.partner_fusion_status/v1",
        "status": parsed["status"],
        "reason": parsed["reason"],
        "promote_live_claim_allowed": bool(parsed["promote_live_claim_allowed"]),
        "live_sha_present": bool(live_sha),
        "status_path": "docs/compliance/partner-fusion-proof.live.status",
        "runbook_path": "docs/compliance/partner-fusion-proof-runbook.md",
        "opensanctions": {
            "plugin": "opensanctions",
            "continuous_screening": "catalog_callable",
            "note": (
                "OpenSanctions is a callable ingress plugin — not Marble Motiva+ES "
                "continuous list productization. Configure API key under Integrations; "
                "do not claim LIVE partner fusion from this plugin alone."
            ),
        },
        "honesty": (
            "WAIVED without real Fingerprint/Incognia credentials. Never forge LIVE pins."
        ),
    }
