"""C1 loyalty feed-gate honesty — mirror S9 keys; do not re-home multi-gate."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Align with loyalty-abuse multi_gate._FEED_LIST_KEYS + refunds required key.
REQUIRED_FEED_LIST_KEYS = ("orders", "loyalty_ledger", "lifecycle")
REQUIRED_FEED_KEYS = ("refunds",) + REQUIRED_FEED_LIST_KEYS

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_STATUS = _REPO_ROOT / "docs" / "compliance" / "loyalty-feeds.status"

_BLOCKING_STATUSES = frozenset(
    {
        "feeds_missing",
        "feeds_incomplete",
        "stale",
        "config_missing",
        "bridge_unconfigured",
        "not_proven",
        "unknown",
    }
)


def status_path() -> Path:
    override = os.environ.get("TARKA_LOYALTY_FEEDS_STATUS_PATH", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_STATUS


def validate_feed_snapshot(feed_snapshot: Any) -> dict[str, Any]:
    """Thin S9 key check. Incomplete/missing never claim-ready (C1)."""
    if feed_snapshot is None:
        return {
            "status": "feeds_missing",
            "present_keys": [],
            "missing_keys": list(REQUIRED_FEED_KEYS),
            "claim_allowed": False,
        }
    if not isinstance(feed_snapshot, dict):
        return {
            "status": "feeds_missing",
            "present_keys": [],
            "missing_keys": list(REQUIRED_FEED_KEYS),
            "claim_allowed": False,
        }
    present = [k for k in REQUIRED_FEED_KEYS if k in feed_snapshot]
    missing: list[str] = []
    if "refunds" not in feed_snapshot:
        missing.append("refunds")
    for key in REQUIRED_FEED_LIST_KEYS:
        val = feed_snapshot.get(key)
        if key not in feed_snapshot:
            missing.append(key)
        elif not isinstance(val, list) or len(val) == 0:
            missing.append(f"{key}:empty")
    if missing:
        return {
            "status": "feeds_incomplete",
            "present_keys": present,
            "missing_keys": missing,
            "claim_allowed": False,
        }
    return {
        "status": "feeds_complete",
        "present_keys": present,
        "missing_keys": [],
        "claim_allowed": False,  # complete snapshot ≠ live tenant warehouse proof
        "note": "Fixture/complete keys only — live claim needs FEEDS_READY status file + tenant warehouse.",
    }


def parse_economics_block(response: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    eco = response.get("economics")
    if isinstance(eco, dict) and eco:
        return eco
    # Some envelopes nest economics under friction payload — ignore non-dicts.
    return None


def economics_feed_status(economics: dict[str, Any] | None) -> str:
    if not isinstance(economics, dict) or not economics:
        return "unknown"
    status = str(economics.get("status") or "").strip().lower()
    return status or "unknown"


def claim_allowed_for_economics_status(status: str) -> bool:
    """Live loyalty-abuse product language — never from incomplete/missing feeds."""
    s = (status or "").strip().lower()
    if s in _BLOCKING_STATUSES or not s:
        return False
    # ok / partial_derived mean multi-gate ran; still need FEEDS_READY ops pin for claim.
    return False


def parse_feeds_status_line(line: str) -> dict[str, Any]:
    text = (line or "").strip()
    if not text:
        return {
            "status": "MISSING",
            "reason": "empty status file",
            "live_claim_allowed": False,
        }
    upper = text.upper()
    if upper.startswith("FEEDS_READY"):
        return {
            "status": "FEEDS_READY",
            "reason": text.split("—", 1)[-1].strip() if "—" in text else "",
            "live_claim_allowed": True,
        }
    if upper.startswith("FEEDS_NOT_PROVEN") or upper.startswith("WAIVED"):
        reason = text.split("—", 1)[-1].strip() if "—" in text else text
        return {
            "status": "FEEDS_NOT_PROVEN",
            "reason": reason,
            "live_claim_allowed": False,
        }
    return {
        "status": "INVALID",
        "reason": text[:200],
        "live_claim_allowed": False,
    }


def load_feeds_status_file(*, path: Path | None = None) -> dict[str, Any]:
    p = path or status_path()
    if not p.is_file():
        return {
            "status": "MISSING",
            "reason": "loyalty-feeds.status absent",
            "live_claim_allowed": False,
            "path": str(p),
        }
    try:
        line = p.read_text(encoding="utf-8").strip().splitlines()[0]
    except (OSError, IndexError):
        return {
            "status": "MISSING",
            "reason": "unreadable status file",
            "live_claim_allowed": False,
            "path": str(p),
        }
    out = parse_feeds_status_line(line)
    out["path"] = str(p)
    out["raw"] = line
    return out


def bridge_configured(*, url: str | None = None, api_key: str | None = None) -> bool:
    u = (url if url is not None else os.environ.get("LOYALTY_ABUSE_URL", "")).strip()
    k = (api_key if api_key is not None else os.environ.get("LOYALTY_ABUSE_API_KEY", "")).strip()
    # Settings may use TARKA_ prefixed names via pydantic — also check those.
    if not u:
        u = os.environ.get("TARKA_LOYALTY_ABUSE_URL", "").strip()
    if not k:
        k = os.environ.get("TARKA_LOYALTY_ABUSE_API_KEY", "").strip()
    return bool(u and k)


def tags_for_feed_status(status: str) -> list[str]:
    s = (status or "").strip().lower()
    if s in {"feeds_missing", "feeds_incomplete", "stale", "config_missing"}:
        return [f"loyalty:{s}"]
    if s in {"feeds_complete", "ok", "partial_derived"}:
        return ["loyalty:feeds_present"]
    return ["loyalty:feeds_unknown"]


def extract_feed_snapshot(
    *,
    metadata: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> Any:
    meta = metadata if isinstance(metadata, dict) else {}
    pl = payload if isinstance(payload, dict) else {}
    for src in (meta, pl):
        for key in ("feed_snapshot", "loyalty_feed_snapshot"):
            if key in src:
                return src.get(key)
    return None


def load_loyalty_feed_ops_posture(
    *,
    loyalty_abuse_url: str = "",
    loyalty_abuse_api_key: str = "",
    status_file: Path | None = None,
) -> dict[str, Any]:
    file_status = load_feeds_status_file(path=status_file)
    configured = bridge_configured(url=loyalty_abuse_url, api_key=loyalty_abuse_api_key)
    blockers: list[str] = []
    if not configured:
        blockers.append("loyalty_bridge_unconfigured")
    if not file_status.get("live_claim_allowed"):
        blockers.append(f"status_{file_status.get('status', 'MISSING')}")
    return {
        "schema_id": "tarka.loyalty_feed_ops_posture/v1",
        "claim_lock": "C1",
        "required_feed_keys": list(REQUIRED_FEED_KEYS),
        "bridge_configured": configured,
        "feeds_status": file_status,
        "live_claim_allowed": bool(
            configured and file_status.get("live_claim_allowed")
        ),
        "blockers": blockers,
        "sibling_smoke": "../loyalty-abuse/scripts/loyalty_economics_feed_smoke.py",
        "tarka_smoke": "scripts/oss/loyalty_feed_posture_smoke.py",
        "honesty": (
            "Graph relatedness ≠ loyalty abuse. Multi-gate LTV stays in loyalty-abuse. "
            "Incomplete/missing feeds never allow live loyalty-abuse product claims. "
            "Do not re-home warehouse feeds into Tarka."
        ),
        "guide": "docs/docs/guides/vertical-packs-marketplace-delivery.md",
    }
