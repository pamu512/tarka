"""Shared decision-intelligence layer: evidence items + AgentRun (bounded agency)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class EvidenceItem:
    """Immutable evidence atom with exact citation identity."""

    evidence_id: str
    source: str
    json_pointer: str
    observation_time: str
    freshness_seconds: float | None
    sensitivity: str
    content_hash: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentRun:
    """Persisted copilot run: omniscient context, zero autonomous authority."""

    agent_run_id: str
    tenant_id: str
    case_id: str | None
    entity_id: str | None
    trace_id: str | None
    prompt_hash: str
    model_provider: str
    model_revision: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    uncertainty: dict[str, Any] = field(default_factory=dict)
    human_review: dict[str, Any] | None = None
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_evidence_item(
    *,
    source: str,
    json_pointer: str,
    value: Any,
    observation_time: str | None = None,
    freshness_seconds: float | None = None,
    sensitivity: str = "internal",
) -> EvidenceItem:
    body = {
        "source": source,
        "json_pointer": json_pointer,
        "value": value,
        "observation_time": observation_time or _utc_now(),
    }
    digest = content_hash(body)
    return EvidenceItem(
        evidence_id=f"ev_{digest[:24]}",
        source=source,
        json_pointer=json_pointer,
        observation_time=body["observation_time"],
        freshness_seconds=freshness_seconds,
        sensitivity=sensitivity,
        content_hash=digest,
        value=value,
    )


def assemble_context_key(
    *,
    tenant_id: str,
    case_id: str | None,
    entity_id: str | None,
    trace_id: str | None,
    evidence_snapshot_hash: str,
) -> str:
    return "|".join(
        [
            (tenant_id or "").strip() or "default",
            (case_id or "").strip() or "-",
            (entity_id or "").strip() or "-",
            (trace_id or "").strip() or "-",
            (evidence_snapshot_hash or "").strip() or "-",
        ]
    )


def new_agent_run(
    *,
    tenant_id: str,
    prompt: str,
    model_provider: str,
    model_revision: str,
    case_id: str | None = None,
    entity_id: str | None = None,
    trace_id: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    evidence_ids: list[str] | None = None,
    claims: list[dict[str, Any]] | None = None,
    uncertainty: dict[str, Any] | None = None,
) -> AgentRun:
    return AgentRun(
        agent_run_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        case_id=case_id,
        entity_id=entity_id,
        trace_id=trace_id,
        prompt_hash=content_hash({"prompt": prompt}),
        model_provider=model_provider,
        model_revision=model_revision,
        tool_calls=list(tool_calls or []),
        evidence_ids=list(evidence_ids or []),
        claims=list(claims or []),
        uncertainty=dict(uncertainty or {}),
    )


def validate_claims_against_evidence(
    claims: list[dict[str, Any]],
    evidence_by_id: dict[str, EvidenceItem],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Require exact evidence_id citations; unsupported claims are marked unsupported."""
    adjustments: list[str] = []
    out: list[dict[str, Any]] = []
    for claim in claims:
        c = dict(claim)
        refs = c.get("evidence_ids") or c.get("citation_ids") or []
        if not isinstance(refs, list) or not refs:
            c["supported"] = False
            c["source"] = "unknown"
            adjustments.append("missing_evidence_id")
            out.append(c)
            continue
        resolved = [str(r) for r in refs if str(r) in evidence_by_id]
        if len(resolved) != len([str(r) for r in refs]):
            c["supported"] = False
            c["source"] = "unknown"
            adjustments.append("unresolved_evidence_id")
        else:
            c["supported"] = True
            c["source"] = "evidence"
            c["evidence_ids"] = resolved
        out.append(c)
    return out, adjustments
