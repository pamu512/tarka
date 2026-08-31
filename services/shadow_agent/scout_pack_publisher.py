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
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

try:
    from decision_api.brain_wire import brain_wire_verdict
except ImportError:  # ponytail: one copy; upgrade is a shared wheel

    def brain_wire_verdict(
        helpfulness: Mapping[str, Any] | None,
        precision: Mapping[str, Any] | None,
        *,
        proposed_rule_ids: Sequence[str],
        fp_cap: float,
    ) -> dict[str, Any]:
        h = helpfulness if isinstance(helpfulness, Mapping) else {}
        blockers = {str(b) for b in (h.get("blockers") or []) if b}
        drop = next(
            (b for b in ("leftover_extras_fp_over_cap", "leftover_extras_no_lift") if b in blockers),
            None,
        )
        if drop:
            return {
                "publish_allowed": False,
                "reason": drop,
                "keep_rule_ids": [],
                "stamp_underpowered": False,
                "should_kill": True,
            }
        keep: list[str] = []
        rules = {
            str(r.get("rule_id") or ""): r
            for r in ((precision or {}).get("rules") or [])
            if isinstance(r, Mapping)
        }
        for rid in proposed_rule_ids:
            token = str(rid or "").strip()
            if not token:
                continue
            row = rules.get(token) or {}
            if bool(row.get("enough_support")) and float(row.get("fp_rate") or 0) > fp_cap:
                continue
            keep.append(token)
        if proposed_rule_ids and not keep:
            return {
                "publish_allowed": False,
                "reason": "rule_fp_over_cap",
                "keep_rule_ids": [],
                "stamp_underpowered": False,
                "should_kill": False,
            }
        return {
            "publish_allowed": True,
            "reason": None,
            "keep_rule_ids": keep,
            "stamp_underpowered": bool(h.get("underpowered")),
            "should_kill": False,
        }


def _attach_decision_api_headers(req: Any, actor: str) -> None:
    """Governance + actor, plus optional API key / internal token."""
    governance_secret = os.environ.get("RULE_GOVERNANCE_SECRET", "").strip()
    if governance_secret:
        req.add_header("X-Rule-Governance-Secret", governance_secret)
    req.add_header("X-Actor", actor)
    api_key = (
        os.environ.get("DECISION_API_KEY")
        or os.environ.get("X_API_KEY")
        or (os.environ.get("API_KEYS") or "").split(",")[0]
        or ""
    ).strip()
    if api_key:
        req.add_header("X-API-Key", api_key)
    internal = (
        os.environ.get("CASE_INTERNAL_TOKEN") or os.environ.get("DECISION_INTERNAL_TOKEN") or ""
    ).strip()
    if internal:
        req.add_header("X-Internal-Token", internal)


async def leftover_gate_payload(
    tenant_id: str,
    *,
    decision_api_url: str | None = None,
    actor: str = "scout_coordinated_burst",
) -> dict[str, Any] | None:
    """GET leftover helpfulness. Non-2xx / exception → None (fail closed)."""
    import urllib.parse
    import urllib.request

    tid = (tenant_id or "").strip()
    if not tid:
        return None
    base = (
        decision_api_url
        or os.environ.get("DECISION_API_URL", "").strip()
        or "http://decision-api:8001"
    )
    url = f"{base.rstrip('/')}/v1/calibration/shadow-promote-gate?{urllib.parse.urlencode({'tenant_id': tid})}"
    req = urllib.request.Request(url, method="GET")
    _attach_decision_api_headers(req, actor)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read())
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _leftover_verdict_for_pack(pack: dict[str, Any], gate: Mapping[str, Any]) -> dict[str, Any]:
    leftover_g = gate.get("leftover_promote_gate") if isinstance(gate, Mapping) else {}
    leftover_g = leftover_g if isinstance(leftover_g, Mapping) else {}
    helpfulness = leftover_g.get("helpfulness")
    if not isinstance(helpfulness, Mapping):
        helpfulness = leftover_g
    precision = gate.get("rule_precision_after_labels") if isinstance(gate, Mapping) else {}
    try:
        fp_cap = float(helpfulness.get("fp_rate_cap") or 0.4)
    except (TypeError, ValueError):
        fp_cap = 0.4
    ids = [
        str(r.get("id") or "").strip()
        for r in (pack.get("rules") or [])
        if isinstance(r, dict) and str(r.get("id") or "").strip()
    ]
    verdict = brain_wire_verdict(helpfulness, precision, proposed_rule_ids=ids, fp_cap=fp_cap)
    if verdict.get("stamp_underpowered"):
        ev = pack.get("evidence")
        if not isinstance(ev, dict):
            ev = {}
            pack["evidence"] = ev
        ev["leftover_helpfulness"] = {
            "labeled_extras": helpfulness.get("labeled_extras"),
            "extra_tp": helpfulness.get("extra_tp"),
            "extra_fp": helpfulness.get("extra_fp"),
            "hint": "helpfulness_underpowered",
        }
    return verdict


def _apply_keep_rule_ids(pack: dict[str, Any], verdict: Mapping[str, Any]) -> bool:
    """Strip pack rules to keep_rule_ids. False if the pack is empty after strip."""
    proposed = [
        r
        for r in (pack.get("rules") or [])
        if isinstance(r, dict) and str(r.get("id") or "").strip()
    ]
    if not proposed:
        return True
    keep = {str(x) for x in (verdict.get("keep_rule_ids") or [])}
    pack["rules"] = [r for r in proposed if str(r.get("id") or "").strip() in keep]
    return bool(pack["rules"])


def _tenant_id(*sources: Mapping[str, Any] | None) -> str:
    for src in sources:
        if not isinstance(src, Mapping):
            continue
        tid = str(src.get("tenant_id") or "").strip()
        if tid:
            return tid
    return ""


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
        _stamp_fingerprint_evidence(pack, report)
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

    tid = _tenant_id(report)
    if not tid:
        return {"published": False, "reason": "leftover_helpfulness_no_tenant"}

    actor = authored_by or "scout_coordinated_burst"
    gate = await leftover_gate_payload(tid, decision_api_url=decision_api_url, actor=actor)
    if gate is None:
        return {"published": False, "reason": "leftover_helpfulness_unavailable"}

    verdict = _leftover_verdict_for_pack(pack, gate)
    if not verdict.get("publish_allowed"):
        return {
            "published": False,
            "reason": str(verdict.get("reason") or "leftover_helpfulness_refused"),
        }
    if not _apply_keep_rule_ids(pack, verdict):
        return {
            "published": False,
            "reason": str(verdict.get("reason") or "rule_fp_over_cap"),
        }

    try:
        pack["tenant_id"] = tid
        resp = _post_pack(pack, decision_api_url=decision_api_url, actor=actor)
        return {"published": True, "pack": pack, "response": resp}
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

            tid = _tenant_id(report, scan_payload)
            if not tid:
                dropped.append({"fingerprint": fk, "reason": "leftover_helpfulness_no_tenant"})
                continue

            actor = authored_by or "scout_coordinated_burst"
            gate = await leftover_gate_payload(
                tid, decision_api_url=decision_api_url, actor=actor
            )
            if gate is None:
                dropped.append({"fingerprint": fk, "reason": "leftover_helpfulness_unavailable"})
                continue

            verdict = _leftover_verdict_for_pack(pack, gate)
            if not verdict.get("publish_allowed"):
                dropped.append(
                    {
                        "fingerprint": fk,
                        "reason": str(verdict.get("reason") or "leftover_helpfulness_refused"),
                    }
                )
                continue
            if not _apply_keep_rule_ids(pack, verdict):
                dropped.append(
                    {
                        "fingerprint": fk,
                        "reason": str(verdict.get("reason") or "rule_fp_over_cap"),
                    }
                )
                continue

            try:
                pack["tenant_id"] = tid
                resp = _post_pack(
                    pack,
                    decision_api_url=decision_api_url,
                    actor=actor,
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
    _attach_decision_api_headers(req, actor)

    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _stamp_fingerprint_evidence(pack: dict[str, Any], report: Mapping[str, Any]) -> None:
    """Durable kill key must match publisher _fingerprint_key after restart."""
    ev = pack.get("evidence")
    if not isinstance(ev, dict):
        ev = {}
        pack["evidence"] = ev
    kind = report.get("fingerprint_kind")
    value = report.get("fingerprint_value")
    if kind:
        ev["fingerprint_kind"] = kind
    if value is not None and str(value) != "":
        ev["fingerprint_value"] = value
    tid = str(report.get("tenant_id") or "").strip()
    if tid and not str(pack.get("tenant_id") or "").strip():
        pack["tenant_id"] = tid


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

    evidence: dict[str, Any] = {}
    raw_ev = report.get("evidence")
    if isinstance(raw_ev, dict):
        evidence.update(raw_ev)
    evidence["fingerprint_kind"] = report.get("fingerprint_kind")
    evidence["fingerprint_value"] = report.get("fingerprint_value")

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
        "tenant_id": report.get("tenant_id"),
        "evidence": evidence,
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
