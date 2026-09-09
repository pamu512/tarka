"""G5.4: optional consume of joined warehouse labels → Observe drafts. Never Active."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from decision_api import label_observe_job


def consume_joined_labels(**kwargs):
    fn = getattr(label_observe_job, "consume_joined_labels", None)
    assert fn is not None, "consume_joined_labels is the buyer-owned batch entry"
    return fn(**kwargs)


def _joined_row(
    token: str,
    kind: str,
    labeled_at: str,
    *,
    entity_id: str = "e1",
) -> dict:
    return {
        "evaluation_token": token,
        "tenant_id": "t1",
        "entity_id": entity_id,
        "label_kind": kind,
        "labeled_at": labeled_at,
    }


def _labels(*rows: dict) -> dict:
    kinds = {r["evaluation_token"]: r["label_kind"] for r in rows}
    stamped = {r["evaluation_token"]: r["labeled_at"] for r in rows}
    return {
        "label_kind_by_trace": kinds,
        "labeled_at_by_trace": stamped,
    }


def test_joined_labels_since_t_mint_observe_live_packs_unchanged() -> None:
    live = {
        "name": "live_pack",
        "mode": "active",
        "authored_by": "human",
        "lifecycle": {"state": "promoted"},
        "rules": [
            {
                "id": "r-live",
                "when": [{"field": "entity_id", "op": "eq", "value": "e-live"}],
                "score_delta": 1,
            }
        ],
    }
    before = deepcopy(live)
    row = _joined_row("tr-new", "fp", "2026-09-08T00:00:00Z")
    minted = consume_joined_labels(
        packs=[live],
        tenant_id="t1",
        training_rows=[row],
        labels=_labels(row),
        since="2026-09-01T00:00:00Z",
    )
    assert minted
    pack = minted[0]
    assert pack["mode"] == "shadow"
    assert pack["lifecycle"]["state"] == "observe"
    assert pack["authored_by"] in {"seed", "system"}
    assert pack["is_ai_authored"] is False
    assert live == before
    assert live["mode"] == "active"
    assert live["lifecycle"]["state"] == "promoted"


def test_consume_second_run_idempotent() -> None:
    row = _joined_row("tr-fp", "chargeback", "2026-09-08T00:00:00Z")
    labels = _labels(row)
    first = consume_joined_labels(
        packs=[],
        tenant_id="t1",
        training_rows=[row],
        labels=labels,
    )
    assert first
    second = consume_joined_labels(
        packs=first,
        tenant_id="t1",
        training_rows=[row],
        labels=labels,
    )
    assert second == []


def test_consume_never_sets_promoted_or_active() -> None:
    src = Path(label_observe_job.__file__).read_text(encoding="utf-8")
    for banned in (
        "mark_promoted",
        "confirm_demote",
        "force_live",
        "force-live",
        "auto_promote",
        "set_pack_mode",
    ):
        assert banned not in src, banned
    row = _joined_row("tr-promo", "promo_abuse", "2026-09-08T00:00:00Z")
    minted = consume_joined_labels(
        packs=[],
        tenant_id="t1",
        training_rows=[row],
        labels=_labels(row),
    )
    assert minted
    for pack in minted:
        assert pack["mode"] == "shadow"
        assert pack["mode"] != "active"
        assert pack["lifecycle"]["state"] == "observe"
        assert pack["lifecycle"]["state"] != "promoted"


def test_since_t_skips_labels_outside_window() -> None:
    old = _joined_row("tr-old", "fp", "2026-01-01T00:00:00Z")
    new = _joined_row("tr-new", "chargeback", "2026-09-08T00:00:00Z")
    missing = _joined_row("tr-bare", "fp", "")
    minted = consume_joined_labels(
        packs=[],
        tenant_id="t1",
        training_rows=[old, new, missing],
        labels=_labels(old, new),
        since="2026-09-01T00:00:00Z",
    )
    traces = {str((p.get("evidence") or {}).get("trace_id") or "") for p in minted}
    assert traces == {"tr-new"}


def test_empty_consume_input_mints_nothing() -> None:
    assert consume_joined_labels(packs=[], tenant_id="t1") == []
    assert (
        consume_joined_labels(
            packs=[],
            tenant_id="t1",
            training_rows=[],
            labels={"label_kind_by_trace": {"tr-x": "fp"}},
        )
        == []
    )


def test_docs_labels_may_propose_observe_only() -> None:
    root = Path(__file__).resolve().parents[3]
    lock = (root / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
    sink = (root / "docs/contracts/warehouse-sink-v1.md").read_text(encoding="utf-8")
    join = (root / "docs/contracts/label-join-v1.md").read_text(encoding="utf-8")
    blob = f"{lock}\n{sink}\n{join}".lower()
    assert "observe draft" in blob
    assert "buyer" in blob
    assert "crm" in blob
    assert "auto-promote" in blob or "auto promote" in blob
    assert "case inbox" in blob or "case crm" in blob
    assert getattr(label_observe_job, "CONSUME_OWNER", None) == "buyer"
    assert getattr(label_observe_job, "CONSUME_IS_CRM", None) is False
    assert getattr(label_observe_job, "CONSUME_AUTO_PROMOTE", None) is False
