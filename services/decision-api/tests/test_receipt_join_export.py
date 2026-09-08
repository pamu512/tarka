"""W2 join keys + export training_rows + label kinds."""

from __future__ import annotations

from pathlib import Path

import pytest

from decision_api.disposition_map import UnknownDisposition, resolve_label_kind
from decision_api.gnn_loop.late_label import LateLabelError, normalize_label_kind
from decision_api.label_observe_job import drafts_from_labels
from decision_api.receipt_export import join_training_rows, write_jsonl
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
