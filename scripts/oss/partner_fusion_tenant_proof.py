#!/usr/bin/env python3
"""Highest-leverage hybrid proof: partner fusion → audit → case evidence + SHA.

Modes:
  fixture (default) — recorded signals, no vendor keys / API required (CI)
  live              — POST evaluate with metadata ids when DECISION_API_URL set;
                      prefers live vendor fetch when adapters+keys configured

Env:
  DECISION_API_URL              base URL for live mode
  FINGERPRINT_REQUEST_ID        metadata.fingerprint_request_id
  INCOGNIA_ACCOUNT_ID           metadata.incognia_account_id
  PARTNER_FUSION_PROOF_TENANT   default proof-tenant
  PARTNER_FUSION_PROOF_OUT      output JSON path (default artifacts/…)
  REQUIRE_LIVE_PARTNER_PROOF=1  exit 1 if live path not used / no partner_evidence
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "partner_fusion_signals.json"
)
_DEFAULT_OUT = _REPO / "artifacts" / "partner-fusion-proof.json"


def _canonical_sha256(obj: dict[str, Any]) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fusion_from_fixture() -> tuple[dict[str, Any], list[str], list[dict], dict]:
    sys.path.insert(0, str(_REPO / "services" / "decision-api" / "src"))
    from decision_api.partner_fusion import graph_writeback_hints, signals_to_feature_tags

    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    sigs = [SimpleNamespace(**row) for row in raw["signals"]]
    feats, tags, evidence = signals_to_feature_tags(sigs)
    hints = graph_writeback_hints(
        tenant_id=os.environ.get("PARTNER_FUSION_PROOF_TENANT", "proof-tenant"),
        entity_id="proof-entity",
        transaction_id="proof-tx",
        tags=tags,
        features=feats,
    )
    return feats, tags, evidence, hints


def _build_case_evidence(
    *,
    tenant_id: str,
    entity_id: str,
    trace_id: str,
    evidence: list[dict[str, Any]],
    hints: dict[str, Any],
    tags: list[str],
    features: dict[str, Any],
) -> dict[str, Any]:
    """Shape aligned with case-api evidence_bundle decision_audit join."""
    return {
        "schema_id": "tarka.evidence_bundle/v1",
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "trace_id": trace_id,
        "decision_audit": {
            "trace_id": trace_id,
            "tags": tags,
            "payload_snapshot": {
                "partner_evidence": evidence,
                "partner_graph_writeback": hints,
                "partner_feature_keys": sorted(features.keys()),
            },
        },
    }


def _fixture_proof(tenant_id: str) -> dict[str, Any]:
    feats, tags, evidence, hints = _fusion_from_fixture()
    trace_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "tarka-partner-fusion-fixture-v1"))
    case_ev = _build_case_evidence(
        tenant_id=tenant_id,
        entity_id="proof-entity",
        trace_id=trace_id,
        evidence=evidence,
        hints=hints,
        tags=tags,
        features=feats,
    )
    body: dict[str, Any] = {
        "schema_id": "tarka.partner_fusion_proof/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "fixture",
        "tenant_id": tenant_id,
        "trace_id": trace_id,
        "fixture": str(_FIXTURE.relative_to(_REPO)),
        "evaluate_path": {
            "features": feats,
            "tags": tags,
        },
        "audit_snapshot": {
            "partner_evidence": evidence,
            "partner_graph_writeback": hints,
        },
        "case_evidence": case_ev,
        "ok": bool(evidence)
        and bool(hints.get("vertices"))
        and bool(hints.get("edges")),
    }
    # Hash without generated_at / content_sha256 for stable CI digests when desired
    hashable = {
        k: v
        for k, v in body.items()
        if k not in ("generated_at", "content_sha256")
    }
    body["content_sha256"] = _canonical_sha256(hashable)
    body["stable_sha256"] = _canonical_sha256(
        {
            "schema_id": body["schema_id"],
            "mode": body["mode"],
            "tenant_id": body["tenant_id"],
            "trace_id": body["trace_id"],
            "fixture": body["fixture"],
            "evaluate_path": body["evaluate_path"],
            "audit_snapshot": body["audit_snapshot"],
            "case_evidence": {
                "schema_id": case_ev["schema_id"],
                "decision_audit": case_ev["decision_audit"],
            },
        }
    )
    return body


def _live_proof(tenant_id: str) -> dict[str, Any]:
    base = os.environ.get("DECISION_API_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("DECISION_API_URL required for live mode")
    fp = os.environ.get("FINGERPRINT_REQUEST_ID", "").strip()
    inc = os.environ.get("INCOGNIA_ACCOUNT_ID", "").strip()
    if not fp and not inc:
        raise RuntimeError(
            "Set FINGERPRINT_REQUEST_ID and/or INCOGNIA_ACCOUNT_ID for live proof"
        )
    metadata: dict[str, Any] = {}
    if fp:
        metadata["fingerprint_request_id"] = fp
    if inc:
        metadata["incognia_account_id"] = inc
    ev = _post_json(
        f"{base}/v1/decisions/evaluate",
        {
            "tenant_id": tenant_id,
            "event_type": "payment",
            "entity_id": "partner-proof-entity",
            "payload": {"amount": 12.0, "currency": "USD", "partner_proof": True},
            "metadata": metadata,
        },
    )
    trace_id = str(ev.get("trace_id") or "")
    audit: dict[str, Any] = {}
    if trace_id:
        try:
            audit = _get_json(f"{base}/v1/audit/{trace_id}")
        except urllib.error.URLError:
            audit = {}
    snap = {}
    if isinstance(audit.get("payload_snapshot"), dict):
        snap = audit["payload_snapshot"]
    elif isinstance(ev.get("payload_snapshot"), dict):
        snap = ev["payload_snapshot"]
    evidence = list(snap.get("partner_evidence") or [])
    hints = snap.get("partner_graph_writeback") or {}
    tags = list(ev.get("tags") or audit.get("tags") or [])
    feats = {
        k: v
        for k, v in (ev.get("features") or {}).items()
        if str(k).startswith("vendor_")
    }
    if not feats and evidence:
        # reconstruct minimal feature view from evidence
        for row in evidence:
            vid = str(row.get("vendor_id") or "vendor")
            feats[f"vendor_{vid}_score"] = row.get("score_0_100")
    case_ev = _build_case_evidence(
        tenant_id=tenant_id,
        entity_id="partner-proof-entity",
        trace_id=trace_id or "unknown",
        evidence=evidence,
        hints=hints if isinstance(hints, dict) else {},
        tags=tags,
        features=feats,
    )
    body: dict[str, Any] = {
        "schema_id": "tarka.partner_fusion_proof/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "live",
        "tenant_id": tenant_id,
        "trace_id": trace_id,
        "decision": ev.get("decision"),
        "metadata_keys": sorted(metadata.keys()),
        "evaluate_path": {"features": feats, "tags": tags},
        "audit_snapshot": {
            "partner_evidence": evidence,
            "partner_graph_writeback": hints,
        },
        "case_evidence": case_ev,
        "ok": bool(evidence),
        "hint": (
            "ok"
            if evidence
            else "no partner_evidence — check vendor keys + request/account ids + adapter registration"
        ),
    }
    hashable = {k: v for k, v in body.items() if k not in ("generated_at", "content_sha256")}
    body["content_sha256"] = _canonical_sha256(hashable)
    return body


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--mode",
        choices=("fixture", "live", "auto"),
        default="auto",
        help="auto: live if DECISION_API_URL set, else fixture",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path(
            os.environ.get("PARTNER_FUSION_PROOF_OUT", str(_DEFAULT_OUT))
        ),
    )
    args = p.parse_args()
    tenant = os.environ.get("PARTNER_FUSION_PROOF_TENANT", "proof-tenant").strip()
    require_live = os.environ.get("REQUIRE_LIVE_PARTNER_PROOF", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    mode = args.mode
    if mode == "auto":
        mode = "live" if os.environ.get("DECISION_API_URL", "").strip() else "fixture"

    try:
        if mode == "live":
            proof = _live_proof(tenant)
        else:
            if require_live:
                print(
                    "REQUIRE_LIVE_PARTNER_PROOF set but mode is fixture",
                    file=sys.stderr,
                )
                return 1
            proof = _fixture_proof(tenant)
    except Exception as e:
        print(f"partner fusion proof failed: {e}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    # Also write a committed-friendly digest sidecar for docs
    digest_path = args.out.with_suffix(".sha256")
    digest_path.write_text(
        f"{proof.get('stable_sha256') or proof.get('content_sha256')}\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": proof.get("ok"), "mode": proof.get("mode"),
                      "sha256": proof.get("stable_sha256") or proof.get("content_sha256"),
                      "out": str(args.out)}, indent=2))
    evidence = list(
        (proof.get("audit_snapshot") or {}).get("partner_evidence") or []
    )
    if require_live and proof.get("mode") != "live":
        print(
            "REQUIRE_LIVE_PARTNER_PROOF: proof mode is not live",
            file=sys.stderr,
        )
        return 1
    if require_live and not evidence:
        print(
            "REQUIRE_LIVE_PARTNER_PROOF: audit_snapshot.partner_evidence empty",
            file=sys.stderr,
        )
        return 1
    if proof.get("mode") == "live" and not evidence:
        print(
            "live proof: no partner_evidence in audit snapshot",
            file=sys.stderr,
        )
        return 1
    return 0 if proof.get("ok") and evidence else 1


if __name__ == "__main__":
    raise SystemExit(main())
