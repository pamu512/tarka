from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

"""Draft evidence-shaped payload for audit export (v0 legacy + optional v1)."""
BundleFormat = Literal["v0", "v1", "dual"]
RedactionLevel = Literal["none", "analyst_view", "export_safe"]


def _caps_for_redaction(level: RedactionLevel) -> tuple[int, int, int]:
    """reply max, claims max, source_refs max."""
    if level == "export_safe":
        return 2000, 15, 20
    if level == "analyst_view":
        return 8000, 40, 50
    # none: minimal truncation for transport only
    return 12000, 60, 80


def _tool_trace_redacted(tool_calls: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for t in tool_calls:
        if not isinstance(t, dict):
            continue
        name = t.get("tool")
        if not isinstance(name, str) or not name.strip():
            continue
        args = t.get("args") if isinstance(t.get("args"), dict) else {}
        if not isinstance(args, dict):
            args = {}
        payload = json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        out.append({"tool": name.strip(), "args_sha256": digest})
    return out[:80]


def _content_sha256_v1(
    *,
    turn_id: str,
    prompt_version: str,
    tool_invocation_count: int,
    narrative_reply: str,
) -> str:
    canonical = {
        "turn_id": turn_id,
        "prompt_version": prompt_version,
        "tool_invocation_count": tool_invocation_count,
        "narrative_reply": narrative_reply,
    }
    raw = json.dumps(canonical, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_evidence_bundle_draft(
    *,
    reply: str,
    claims: list[dict[str, str]],
    source_refs: list[dict[str, Any]],
    answer_sections: dict[str, Any],
    claims_analysis: list[dict[str, Any]] | None,
    tool_calls: list[dict[str, Any]],
    prompt_version: str,
    playbook_id: str | None,
    turn_id: str,
    bundle_format: BundleFormat = "dual",
    contract_version: str = "",
    agent_build: str = "",
    redaction_level: RedactionLevel = "analyst_view",
) -> dict[str, Any]:
    """
    Portable snapshot for human review / evidence-bundle alignment.

    - v0: legacy `schema_hint` only (tarka.evidence_bundle_draft/v0).
    - v1: `schema_id` tarka.evidence_bundle/v1 + provenance fields.
    - dual: both (migration default).
    """
    reply_cap, claims_cap, refs_cap = _caps_for_redaction(redaction_level)
    narrative_reply = (reply or "")[:reply_cap]

    base: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "turn_id": turn_id,
        "prompt_version": prompt_version,
        "playbook_id": playbook_id,
        "narrative": {"reply": narrative_reply},
        "structured_sections": {
            k: v for k, v in (answer_sections or {}).items() if k != "sections_found"
        },
        "claims": (claims or [])[:claims_cap],
        "claims_analysis": (claims_analysis or [])[: claims_cap * 2],
        "source_refs": (source_refs or [])[:refs_cap],
        "tool_invocation_count": len(tool_calls),
    }

    if bundle_format in ("v0", "dual"):
        base["schema_hint"] = "tarka.evidence_bundle_draft/v0"

    if bundle_format in ("v1", "dual"):
        base["schema_id"] = "tarka.evidence_bundle/v1"
        base["contract_version"] = (contract_version or "").strip() or "unknown"
        ab = (agent_build or "").strip()
        if ab:
            base["agent_build"] = ab[:256]
        base["redaction_level"] = redaction_level
        base["tool_trace_redacted"] = _tool_trace_redacted(tool_calls)
        base["content_sha256"] = _content_sha256_v1(
            turn_id=turn_id,
            prompt_version=prompt_version,
            tool_invocation_count=len(tool_calls),
            narrative_reply=narrative_reply,
        )

    if bundle_format == "v0":
        for k in (
            "schema_id",
            "contract_version",
            "agent_build",
            "redaction_level",
            "tool_trace_redacted",
            "content_sha256",
        ):
            base.pop(k, None)

    return base
