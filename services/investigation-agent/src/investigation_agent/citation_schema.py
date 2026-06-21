"""Standardized copilot citation schema (OpenAPI + chat/evidence responses)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CITATION_SCHEMA_VERSION = "1.0.0"


class CitationArtifact(str, Enum):
    DECISION_TRACE = "decision_trace"
    CASE = "case"
    JSON_RULE = "json_rule"
    TYPOLOGY = "typology"
    TOOL = "tool"
    UNKNOWN = "unknown"


class CitationResolvesTo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: CitationArtifact | str
    id: str = Field(..., min_length=1, max_length=256)


class CopilotCitation(BaseModel):
    """Canonical citation card shared by ``/v1/chat`` and ``/v1/evidence/summary``."""

    model_config = ConfigDict(extra="forbid")

    claim_index: int = Field(..., ge=0)
    text: str = Field(..., min_length=1, max_length=8192)
    source: Literal["tool", "unknown"] = "unknown"
    supported: bool | None = None
    confidence_label: Literal["low", "medium", "high"] = "low"
    resolves_to: list[CitationResolvesTo] = Field(default_factory=list)


class CitationVerifierSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CITATION_SCHEMA_VERSION
    citation_count: int = Field(..., ge=0)
    supported_count: int = Field(..., ge=0)
    high_confidence_count: int = Field(..., ge=0)
    medium_confidence_count: int = Field(..., ge=0)
    low_confidence_count: int = Field(..., ge=0)
    validity_rate: float = Field(..., ge=0.0, le=1.0)


def _confidence_for_claim(*, source: str, supported: bool | None) -> Literal["low", "medium", "high"]:
    if supported is True:
        return "high"
    if source == "tool":
        return "medium"
    return "low"


def _merge_resolution_refs(*groups: list[dict[str, str]] | None) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for group in groups:
        if not group:
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            artifact = str(item.get("artifact") or "").strip()
            ref_id = str(item.get("id") or "").strip()
            if not artifact or not ref_id:
                continue
            key = (artifact, ref_id)
            if key in seen:
                continue
            seen.add(key)
            out.append({"artifact": artifact, "id": ref_id})
    return out


def build_standard_citations(
    *,
    claims: list[dict[str, Any]],
    deterministic_support: list[dict[str, Any]] | None = None,
    trace_id: str | None = None,
    case_id: str | None = None,
    audit_resolution_refs: list[dict[str, str]] | None = None,
    max_citations: int = 12,
) -> tuple[list[dict[str, Any]], CitationVerifierSummary]:
    supports_by_idx: dict[int, bool] = {}
    for row in deterministic_support or []:
        if not isinstance(row, dict):
            continue
        idx = row.get("claim_index")
        ok = row.get("supported")
        if isinstance(idx, int) and isinstance(ok, bool):
            supports_by_idx[idx] = ok

    citations: list[dict[str, Any]] = []
    for i, claim in enumerate(claims[: max(1, max_citations)]):
        if not isinstance(claim, dict):
            continue
        text = str(claim.get("text") or "").strip()
        if not text:
            continue
        source_raw = str(claim.get("source") or "unknown")
        source: Literal["tool", "unknown"] = "tool" if source_raw == "tool" else "unknown"
        supported = supports_by_idx.get(i)
        confidence = _confidence_for_claim(source=source, supported=supported)

        resolves: list[dict[str, str]] = []
        raw_resolves = claim.get("resolves_to")
        if isinstance(raw_resolves, list):
            for x in raw_resolves:
                if isinstance(x, dict):
                    resolves.append(
                        {"artifact": str(x.get("artifact") or ""), "id": str(x.get("id") or "")},
                    )
        if i == 0 and trace_id:
            resolves.append({"artifact": CitationArtifact.DECISION_TRACE.value, "id": trace_id.strip()})
        if i == 0 and case_id:
            resolves.append({"artifact": CitationArtifact.CASE.value, "id": case_id.strip()})
        merged = _merge_resolution_refs(resolves, audit_resolution_refs if i == 0 else [])

        card = CopilotCitation(
            claim_index=i,
            text=text,
            source=source,
            supported=supported,
            confidence_label=confidence,
            resolves_to=[
                CitationResolvesTo(
                    artifact=str(r.get("artifact") or CitationArtifact.UNKNOWN.value),
                    id=str(r.get("id") or ""),
                )
                for r in merged
                if str(r.get("id") or "").strip()
            ],
        )
        citations.append(card.model_dump(mode="json"))

    supported_ct = sum(1 for c in citations if c.get("supported") is True)
    summary = CitationVerifierSummary(
        citation_count=len(citations),
        supported_count=supported_ct,
        high_confidence_count=sum(1 for c in citations if c.get("confidence_label") == "high"),
        medium_confidence_count=sum(1 for c in citations if c.get("confidence_label") == "medium"),
        low_confidence_count=sum(1 for c in citations if c.get("confidence_label") == "low"),
        validity_rate=round(supported_ct / max(len(citations), 1), 3),
    )
    return citations, summary
