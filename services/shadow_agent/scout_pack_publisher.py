"""Persist a scout hypothesis suggestion as an Observe-only (shadow) rule pack.

The pack lands in the decision-api ``rules_path`` with ``mode=shadow`` so the
Observe page lists it and shadow evaluation covers it, but it never affects live
decisions until an analyst promotes it through the existing label/McNemar/drift
gates.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def scout_report_to_shadow_pack(report: dict[str, Any]) -> dict[str, Any]:
    """Convert a scout hypothesis report dict into a valid shadow-mode rule pack.

    The returned dict is ready to POST to ``/v1/rules/scout-pack`` or write
    directly to the decision-api ``rules_path`` directory.
    """
    suggested_rule = report.get("suggested_rule")
    if not isinstance(suggested_rule, dict):
        raise ValueError("report missing suggested_rule")

    fp_kind = report.get("fingerprint_kind", "unknown")
    fp_value = str(report.get("fingerprint_value", ""))[:40]
    report_id = report.get("report_id") or str(uuid.uuid4())

    rule = dict(suggested_rule)
    rule.setdefault("id", f"scout_{fp_kind}_{uuid.uuid4().hex[:8]}")

    return {
        "version": 1,
        "name": f"Scout: {fp_kind} {fp_value}".strip(),
        "mode": "shadow",
        "rules": [rule],
        "tag_rules": [],
        "canary_percent": None,
        "effective_at": None,
        "approved_by": None,
        "authored_by": "scout_coordinated_burst",
        "is_ai_authored": True,
        "scout_report_id": report_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def publish_scout_pack_http(
    report: dict[str, Any],
    *,
    decision_api_url: str | None = None,
) -> dict[str, Any]:
    """POST the scout shadow pack to the decision-api ``/v1/rules/scout-pack`` endpoint.

    Returns the JSON response on success, raises on HTTP/network failure.
    """
    import urllib.request
    import urllib.error

    base = (
        decision_api_url
        or os.environ.get("DECISION_API_URL", "").strip()
        or "http://decision-api:8001"
    )
    url = f"{base.rstrip('/')}/v1/rules/scout-pack"

    pack = scout_report_to_shadow_pack(report)
    body = json.dumps(pack).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    governance_secret = os.environ.get("RULE_GOVERNANCE_SECRET", "").strip()
    if governance_secret:
        req.add_header("X-Rule-Governance-Secret", governance_secret)
    req.add_header("X-Actor", "scout_coordinated_burst")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:512]
        logger.error("scout_pack_publish_failed status=%s detail=%s", exc.code, detail)
        raise
    except Exception:
        logger.exception("scout_pack_publish_failed")
        raise
