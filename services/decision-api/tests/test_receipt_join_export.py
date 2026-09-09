"""W2 join keys + export training_rows + label kinds. G5.1 consume joinability."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from decision_api import receipt_export, receipt_join
from decision_api.disposition_map import UnknownDisposition, resolve_label_kind
from decision_api.gnn_loop.late_label import LateLabelError, normalize_label_kind
from decision_api.gnn_loop.snapshot import snapshot_from_written
from decision_api.label_observe_job import drafts_from_labels
from decision_api.receipt_export import (
    join_training_rows,
    receipt_row_from_audit,
    write_jsonl,
)
from decision_api.receipt_join import join_keys_from_event


def test_join_keys_required_and_optional() -> None:
    out = join_keys_from_event(
        trace_id="tr-1",
        tenant_id="t1",
        entity_id="e1",
        payload={"promo_id": "p9", "invented": "no"},
    )
    assert out["evaluation_token"] == "tr-1"
    assert out["promo_id"] == "p9"
    assert "courier_id" not in out


def test_party_entity_type_refused() -> None:
    from pydantic import ValidationError

    from decision_api.schemas import EvaluatePartyIn

    EvaluatePartyIn(role="courier", entity_id="c1", entity_type="user")
    with pytest.raises(ValidationError):
        EvaluatePartyIn(role="courier", entity_id="c1", entity_type="sibling")


def test_join_keys_fail_closed() -> None:
    with pytest.raises(ValueError):
        join_keys_from_event(trace_id="", tenant_id="t", entity_id="e")


@pytest.mark.parametrize(
    "kind", ["fp", "fraud", "other", "promo_abuse", "collusion", "chargeback"]
)
def test_label_kinds_normalize(kind: str) -> None:
    assert normalize_label_kind(kind) == kind


def test_unknown_label_kind() -> None:
    with pytest.raises(LateLabelError) as exc:
        normalize_label_kind("not_a_kind")
    assert exc.value.code == "invalid_label_kind"


def test_disposition_map_and_unknown() -> None:
    assert resolve_label_kind({"disposition_code": "confirmed_fraud"}) == "fraud"
    assert (
        resolve_label_kind({"label_kind": "fp", "disposition_code": "confirmed_fraud"})
        == "fp"
    )
    with pytest.raises(UnknownDisposition):
        resolve_label_kind({"disposition_code": "unknown"})


def test_export_join_roundtrip(tmp_path: Path) -> None:
    receipts = [
        {
            "evaluation_token": "tr-1",
            "tenant_id": "t1",
            "entity_id": "e1",
            "decision": "deny",
            "pack_hash": "abc",
        }
    ]
    labels = {
        "label_kind_by_trace": {"tr-1": "chargeback"},
        "fp_cost_by_trace": {},
        "labeled_at_by_trace": {"tr-1": "2026-09-08T00:00:00Z"},
    }
    rows = join_training_rows(receipts, labels)
    assert rows[0]["evaluation_token"] == "tr-1"
    assert rows[0]["label_kind"] == "chargeback"
    dest = tmp_path / "rows.jsonl"
    write_jsonl(dest, rows)
    assert "chargeback" in dest.read_text(encoding="utf-8")


def test_label_job_observe_only_idempotent() -> None:
    labels = {"label_kind_by_trace": {"tr-fp": "fp"}}
    first = drafts_from_labels(packs=[], labels=labels, tenant_id="t1")
    assert first and first[0]["mode"] == "shadow"
    second = drafts_from_labels(packs=first, labels=labels, tenant_id="t1")
    assert second == []


def _audit(**overrides: object) -> SimpleNamespace:
    rec = SimpleNamespace(
        trace_id="tr-1",
        tenant_id="t1",
        entity_id="e1",
        event_type="login",
        decision="allow",
        score=0.0,
        payload_snapshot={"evaluation_token": "tr-1"},
        created_at=None,
    )
    for key, value in overrides.items():
        setattr(rec, key, value)
    return rec


def test_export_row_has_required_join_keys() -> None:
    row = receipt_row_from_audit(_audit())
    for key in ("evaluation_token", "trace_id", "tenant_id", "entity_id"):
        assert str(row.get(key) or "").strip(), key


def test_new_evaluate_receipt_missing_keys_fail_closed() -> None:
    require = getattr(receipt_join, "require_join_keys", None)
    assert require is not None
    with pytest.raises(ValueError):
        require({"whitelisted": True, "reason": "vip"})


def test_stamp_join_keys_on_new_evaluate_receipt() -> None:
    stamp = getattr(receipt_join, "stamp_join_keys", None)
    assert stamp is not None
    snap = stamp(
        {"whitelisted": True},
        trace_id="tr-1",
        tenant_id="t1",
        entity_id="e1",
        payload={"promo_id": "p9", "invented": "no"},
    )
    assert snap["evaluation_token"] == "tr-1"
    assert snap["trace_id"] == "tr-1"
    assert snap["tenant_id"] == "t1"
    assert snap["entity_id"] == "e1"
    assert snap["promo_id"] == "p9"
    assert "invented" not in snap
    receipt_join.require_join_keys(snap)


def test_export_row_copies_optional_party_keys() -> None:
    row = receipt_row_from_audit(
        _audit(
            payload_snapshot={
                "evaluation_token": "tr-1",
                "promo_id": "p9",
                "invented": "no",
            }
        )
    )
    assert row["promo_id"] == "p9"
    assert "invented" not in row


def test_export_row_rejects_blank_required_join_keys() -> None:
    with pytest.raises(ValueError):
        receipt_row_from_audit(_audit(trace_id="", tenant_id="", entity_id=""))


def test_graph_written_snapshot_includes_evaluation_token() -> None:
    snap = snapshot_from_written(
        {
            "nodes": [
                {
                    "id": "u1",
                    "kind": "user",
                    "role": "buyer",
                    "vtype": "user",
                    "tenant_id": "acme",
                }
            ],
            "edges": [],
        },
        trace_id="t-join",
        entity_id="u1",
        user_id="u1",
        role="buyer",
        tenant_id="acme",
    )
    assert snap["evaluation_token"] == "t-join"
    assert snap["trace_id"] == "t-join"
    assert snap["tenant_id"] == "acme"
    assert snap["entity_id"] == "u1"


def test_consume_contract_buyer_owned_not_crm() -> None:
    assert getattr(receipt_export, "CONSUME_OWNER", None) == "buyer"
    assert getattr(receipt_export, "CONSUME_IS_CRM", None) is False
    key_fn = getattr(receipt_export, "consume_idempotency_key", None)
    assert key_fn is not None
    a = key_fn(
        tenant_id="t1",
        window_from="2026-01-01T00:00:00Z",
        window_to="2026-01-02T00:00:00Z",
        evaluation_token="tr-1",
    )
    b = key_fn(
        tenant_id="t1",
        window_from="2026-01-01T00:00:00Z",
        window_to="2026-01-02T00:00:00Z",
        evaluation_token="tr-1",
    )
    assert a == b
    assert "tr-1" in a
    assert "t1" in a


def test_warehouse_sink_documents_scheduled_consume() -> None:
    root = Path(__file__).resolve().parents[3]
    sink = (root / "docs/contracts/warehouse-sink-v1.md").read_text(encoding="utf-8")
    bakeoff = (root / "docs/docs/guides/bakeoff-sop.md").read_text(encoding="utf-8")
    blob = f"{sink}\n{bakeoff}".lower()
    assert "idempoten" in blob
    assert "cron" in blob or "schedule" in blob
    assert "evaluation_token" in sink
    assert "crm" in blob
    assert "buyer" in blob
