"""Persist a scout hypothesis suggestion as an Observe-only (shadow) rule pack.

The pack lands in the decision-api ``rules_path`` with ``mode=shadow`` so the
Observe page lists it and shadow evaluation covers it, but it never affects live
decisions until an analyst promotes it through the existing label/McNemar/drift
gates.

When ``SHADOW_LLM_BACKEND`` + ``SHADOW_LLM_BASE_URL`` are set, the publish
path calls the LLM to author the pack from the hypothesis report.  If the LLM
is not configured the deterministic ``suggested_shadow_rule`` template is used.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _llm_backend_configured() -> bool:
    """True when a BYO LLM backend is set for pack authoring."""
    backend = (os.environ.get("SHADOW_LLM_BACKEND") or "").strip().lower()
    return bool(backend and backend != "ollama")


def _resolve_authored_by() -> str:
    """Derive ``authored_by`` from the configured LLM backend name."""
    raw = (os.environ.get("SHADOW_LLM_BACKEND") or "").strip().lower().replace("-", "_")
    if raw in ("self_hosted", "openai_compat", "openai_compatible"):
        return "self_hosted"
    return raw or "scout"


async def build_scout_pack(
    report: dict[str, Any],
    *,
    llm_client: Any | None = None,
    authored_by: str | None = None,
) -> dict[str, Any] | None:
    """Build a validated scout observe pack.

    When *llm_client* is provided the pack is authored by the LLM via
    ``author_pack_from_hypothesis``; validation failures return ``None``
    (drop — do not publish).

    When *llm_client* is ``None`` the deterministic template path is used
    (``scout_report_to_shadow_pack``).
    """
    if llm_client is not None:
        from pack_author_llm import author_pack_from_hypothesis

        result = await author_pack_from_hypothesis(
            report,
            llm_client,
            authored_by=authored_by or "scout",
        )
        if not result["ok"]:
            logger.warning(
                "scout_pack_llm_rejected errors=%s",
                result.get("errors"),
            )
            return None
        pack = result["pack"]
        # Carry over scout_report_id for provenance
        pack.setdefault("scout_report_id", report.get("report_id"))
        pack.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        return pack

    return scout_report_to_shadow_pack(report)


async def publish_scout_pack(
    report: dict[str, Any],
    *,
    decision_api_url: str | None = None,
) -> dict[str, Any]:
    """LLM-aware publish: author via LLM when configured, else deterministic template.

    Returns ``{"published": True, "pack": {...}, "response": {...}}`` on success,
    ``{"published": False, "reason": "..."}`` when dropped.
    """
    import urllib.request
    import urllib.error

    llm_client = None
    authored_by: str | None = None
    if _llm_backend_configured():
        from llm_client import build_shadow_llm_client

        llm_client = build_shadow_llm_client()
        authored_by = _resolve_authored_by()

    try:
        pack = await build_scout_pack(
            report,
            llm_client=llm_client,
            authored_by=authored_by,
        )
    finally:
        if llm_client is not None and hasattr(llm_client, "aclose"):
            await llm_client.aclose()

    if pack is None:
        return {"published": False, "reason": "pack_rejected_by_validation"}

    base = (
        decision_api_url
        or os.environ.get("DECISION_API_URL", "").strip()
        or "http://decision-api:8001"
    )
    url = f"{base.rstrip('/')}/v1/rules/scout-pack"
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
    req.add_header("X-Actor", authored_by or "scout_coordinated_burst")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {
                "published": True,
                "pack": pack,
                "response": json.loads(resp.read()),
            }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:512]
        logger.error("scout_pack_publish_failed status=%s detail=%s", exc.code, detail)
        raise
    except Exception:
        logger.exception("scout_pack_publish_failed")
        raise


# ponytail: in-memory dedup — survives within process lifetime only.
# Upgrade path: query decision-api for existing scout packs on startup.
_published_fingerprints: set[tuple[str, str]] = set()


def _fingerprint_key(report: dict[str, Any]) -> tuple[str, str]:
    return (
        str(report.get("fingerprint_kind", "")),
        str(report.get("fingerprint_value", "")),
    )


async def publish_scout_burst_packs(
    scan_payload: dict[str, Any],
    *,
    decision_api_url: str | None = None,
) -> dict[str, Any]:
    """Publish packs for all gate-passed hypothesis reports in one scan result.

    Deduplicates on ``(fingerprint_kind, fingerprint_value)`` so a second probe
    with the same burst does not write a second pack.

    Returns ``{"published": [...], "skipped": [...], "dropped": [...]}``.
    """
    reports = scan_payload.get("hypothesis_reports") or []
    published: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    llm_client = None
    authored_by: str | None = None
    if _llm_backend_configured():
        from llm_client import build_shadow_llm_client

        llm_client = build_shadow_llm_client()
        authored_by = _resolve_authored_by()

    try:
        for report in reports:
            fk = _fingerprint_key(report)
            if fk in _published_fingerprints:
                skipped.append({"fingerprint": fk, "reason": "already_published"})
                continue

            pack = await build_scout_pack(
                report,
                llm_client=llm_client,
                authored_by=authored_by,
            )
            if pack is None:
                dropped.append(
                    {
                        "fingerprint": fk,
                        "reason": "pack_rejected_by_validation",
                    }
                )
                logger.info(
                    "scout_burst_pack_dropped fp_kind=%s fp_value=%s",
                    fk[0],
                    fk[1],
                )
                continue

            try:
                resp = _post_pack(
                    pack,
                    decision_api_url=decision_api_url,
                    actor=authored_by or "scout_coordinated_burst",
                )
                _published_fingerprints.add(fk)
                published.append(
                    {
                        "fingerprint": fk,
                        "pack_name": pack.get("name"),
                        "response": resp,
                    }
                )
            except Exception:
                logger.exception(
                    "scout_burst_pack_post_failed fp_kind=%s fp_value=%s",
                    fk[0],
                    fk[1],
                )
                dropped.append({"fingerprint": fk, "reason": "post_failed"})
    finally:
        if llm_client is not None and hasattr(llm_client, "aclose"):
            await llm_client.aclose()

    return {"published": published, "skipped": skipped, "dropped": dropped}


def _post_pack(
    pack: dict[str, Any],
    *,
    decision_api_url: str | None = None,
    actor: str = "scout_coordinated_burst",
) -> dict[str, Any]:
    """POST a validated pack to decision-api (sync, urllib)."""
    import urllib.request
    import urllib.error

    base = (
        decision_api_url
        or os.environ.get("DECISION_API_URL", "").strip()
        or "http://decision-api:8001"
    )
    url = f"{base.rstrip('/')}/v1/rules/scout-pack"
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
    req.add_header("X-Actor", actor)

    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


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

    pack: dict[str, Any] = {
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

    from pack_author_contract import validate_ai_authored_pack

    result = validate_ai_authored_pack(pack)
    if not result["ok"]:
        raise ValueError(f"scout pack rejected by AI author contract: {result['errors']}")

    return pack


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
