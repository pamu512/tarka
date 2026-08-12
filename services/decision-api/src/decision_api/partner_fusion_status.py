"""Read machine-readable L2 partner fusion LIVE|WAIVED status (P0-L2)."""

from __future__ import annotations

import os
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


def load_partner_fusion_status_core(
    *,
    repo_root: Path | None = None,
    status_path: Path | None = None,
    live_sha_path: Path | None = None,
) -> dict[str, Any]:
    """Status parse without nesting live_readiness (avoids recursion)."""
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
        "status": parsed["status"],
        "reason": parsed["reason"],
        "promote_live_claim_allowed": bool(parsed["promote_live_claim_allowed"]),
        "live_sha_present": bool(live_sha),
    }


def _env_configured(*names: str) -> bool:
    return all(bool(os.environ.get(n, "").strip()) for n in names)


def l2_live_readiness(
    *,
    status_core: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Operator checklist toward LIVE — never invents credentials or SHA."""
    fp = bool(os.environ.get("TARKA_VENDOR_FINGERPRINT_API_KEY", "").strip()) or bool(
        os.environ.get("FINGERPRINT_API_KEY", "").strip()
    )
    incognia = _env_configured(
        "TARKA_VENDOR_INCOGNIA_CLIENT_ID", "TARKA_VENDOR_INCOGNIA_CLIENT_SECRET"
    ) or _env_configured("INCOGNIA_CLIENT_ID", "INCOGNIA_CLIENT_SECRET")
    decision_url = bool(os.environ.get("DECISION_API_URL", "").strip())
    req_ids = bool(os.environ.get("FINGERPRINT_REQUEST_ID", "").strip()) or bool(
        os.environ.get("INCOGNIA_ACCOUNT_ID", "").strip()
    )
    status = status_core or load_partner_fusion_status_core()
    blockers: list[str] = []
    if status["status"] == "LIVE" and status.get("live_sha_present"):
        return {
            "ready_to_claim_live": True,
            "ready_to_attempt_live_proof": True,
            "blockers": [],
            "checks": {
                "fingerprint_key_configured": fp,
                "incognia_configured": incognia,
                "decision_api_url": decision_url,
                "request_ids_for_proof": req_ids,
                "status": status["status"],
                "live_sha_present": status.get("live_sha_present"),
            },
            "operator_script": "scripts/oss/partner_fusion_tenant_proof.py --mode live",
        }
    if not (fp or incognia):
        blockers.append("vendor_credentials_missing")
    if not decision_url:
        blockers.append("DECISION_API_URL_unset")
    if not req_ids:
        blockers.append("FINGERPRINT_REQUEST_ID_or_INCOGNIA_ACCOUNT_ID_unset")
    if status["status"] == "WAIVED":
        blockers.append("status_still_WAIVED")
    if status["status"] == "LIVE" and not status.get("live_sha_present"):
        blockers.append("LIVE_without_sha")
    return {
        "ready_to_claim_live": False,
        "ready_to_attempt_live_proof": bool(fp or incognia)
        and decision_url
        and req_ids,
        "blockers": blockers,
        "checks": {
            "fingerprint_key_configured": fp,
            "incognia_configured": incognia,
            "decision_api_url": decision_url,
            "request_ids_for_proof": req_ids,
            "status": status["status"],
            "live_sha_present": bool(status.get("live_sha_present")),
        },
        "operator_script": "scripts/oss/partner_fusion_tenant_proof.py --mode live",
        "runbook": "docs/compliance/partner-fusion-proof-runbook.md",
    }


def load_partner_fusion_status(
    *,
    repo_root: Path | None = None,
    status_path: Path | None = None,
    live_sha_path: Path | None = None,
) -> dict[str, Any]:
    core = load_partner_fusion_status_core(
        repo_root=repo_root,
        status_path=status_path,
        live_sha_path=live_sha_path,
    )
    return {
        "schema_id": "tarka.partner_fusion_status/v1",
        **core,
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
        "live_readiness": l2_live_readiness(status_core=core),
    }
