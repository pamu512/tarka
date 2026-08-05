"""Hybrid enrichment: fuse Fingerprint / Incognia vendor signals into evaluate features."""

from __future__ import annotations

import uuid
from typing import Any, Protocol


# ponytail: duck-type signals so unit tests don't import vendors/ (tenacity, httpx stack)
class PartnerSignal(Protocol):
    vendor_id: str
    score_0_100: float
    reason_codes: list[str]
    raw_meta: dict[str, Any]


def signals_to_feature_tags(
    signals: list[PartnerSignal],
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    """Map normalized vendor signals → feature deltas, tags, inference evidence rows."""
    features: dict[str, Any] = {}
    tags: list[str] = []
    evidence: list[dict[str, Any]] = []
    for sig in signals:
        vendor = (sig.vendor_id or "vendor").strip().lower()
        score = float(sig.score_0_100)
        features[f"vendor_{vendor}_score"] = score
        tag = f"vendor:{vendor}"
        if tag not in tags:
            tags.append(tag)
        for code in sig.reason_codes or []:
            c = str(code).strip().lower().replace(" ", "_")[:64]
            if c:
                ct = f"vendor:{vendor}:{c}"
                if ct not in tags:
                    tags.append(ct)
        meta = sig.raw_meta if isinstance(sig.raw_meta, dict) else {}
        evidence.append(
            {
                "vendor_id": vendor,
                "score_0_100": score,
                "reason_codes": list(sig.reason_codes or []),
                "raw_meta_keys": sorted(str(k) for k in meta.keys())[:32],
            }
        )
        if vendor == "fingerprint":
            for key in ("visitor_id", "request_id", "device_id"):
                if meta.get(key):
                    features["vendor_fingerprint_id"] = str(meta[key])[:256]
                    break
        if vendor == "incognia":
            features["vendor_incognia_risk"] = score
            if meta.get("place_id"):
                features["vendor_incognia_place_id"] = str(meta["place_id"])[:256]
    return features, tags, evidence


def graph_writeback_hints(
    *,
    tenant_id: str,
    entity_id: str,
    transaction_id: str,
    tags: list[str],
    features: dict[str, Any],
) -> dict[str, Any]:
    """Hints for orchestrator/graph-service to MERGE device/place vertices from partners."""
    vertices: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    fp = features.get("vendor_fingerprint_id")
    if fp:
        vertices.append(
            {
                "label": "Device",
                "id": f"fp:{fp}",
                "props": {"source": "fingerprint", "tenant_id": tenant_id},
            }
        )
        edges.append(
            {
                "type": "USED_DEVICE",
                "from": {"label": "Entity", "id": entity_id},
                "to": {"label": "Device", "id": f"fp:{fp}"},
                "props": {
                    "observed_at": "evaluate",
                    "transaction_id": transaction_id,
                    "source": "fingerprint",
                },
            }
        )
    if any(t.startswith("vendor:incognia") for t in tags) or features.get(
        "vendor_incognia_risk"
    ) is not None:
        place_id = str(
            features.get("vendor_incognia_place_id")
            or f"incognia:{tenant_id}:{entity_id}"
        )
        vertices.append(
            {
                "label": "Place",
                "id": place_id,
                "props": {"source": "incognia", "tenant_id": tenant_id},
            }
        )
        edges.append(
            {
                "type": "SEEN_AT",
                "from": {"label": "Entity", "id": entity_id},
                "to": {"label": "Place", "id": place_id},
                "props": {
                    "observed_at": "evaluate",
                    "transaction_id": transaction_id,
                    "source": "incognia",
                },
            }
        )
    return {
        "schema_id": "tarka.partner_graph_writeback/v1",
        "vertices": vertices,
        "edges": edges,
    }


async def maybe_fetch_partner_signals(
    *,
    http: Any,
    session: Any,
    metadata: dict[str, Any],
    tenant_id: str,
    entity_id: str,
    trace_id: str,
) -> list[Any]:
    """Fetch configured partner plugins when metadata carries request identifiers."""
    from decision_api.vendors.registry import get_adapter

    out: list[Any] = []
    try:
        tid = uuid.UUID(str(trace_id))
    except ValueError:
        tid = uuid.uuid4()

    fp_rid = str(metadata.get("fingerprint_request_id") or "").strip()
    if fp_rid:
        adapter = get_adapter("fingerprint")
        if adapter is not None:
            try:
                sig = await adapter.fetch_signal(
                    http,
                    tenant_id,
                    entity_id,
                    {"request_id": fp_rid},
                    budget_ms=800.0,
                    audit_session=session,
                    trace_id=tid,
                )
                out.append(sig)
            except Exception:
                pass
    inc_account = str(metadata.get("incognia_account_id") or "").strip()
    if inc_account:
        adapter = get_adapter("incognia")
        if adapter is not None:
            try:
                sig = await adapter.fetch_signal(
                    http,
                    tenant_id,
                    entity_id,
                    {"account_id": inc_account},
                    budget_ms=800.0,
                    audit_session=session,
                    trace_id=tid,
                )
                out.append(sig)
            except Exception:
                pass
    return out
