"""G2.2: G2.1 ring tags → Observe/shadow drafts. Never auto Active."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from decision_api import ring_job
from decision_api.ring_job import JOB_REQUEST_SCHEMA, run_ring_job

_EVALUATE_DIR = Path(__file__).resolve().parents[1] / "src/decision_api/evaluate"
_WRITER_NEEDLES = (
    "write_ring_observe_drafts",
    "observe_drafts_from_ring",
    "from decision_api.ring_job",
    "import ring_job",
    "run_ring_job",
)
_BANNED_WRITER = (
    "mark_promoted",
    "confirm_demote",
    "confirm_promote",
    "auto_promote",
    "force_live",
    "set_pack_mode",
    "force-live",
)


def write_ring_observe_drafts(**kwargs):
    fn = getattr(ring_job, "write_ring_observe_drafts", None)
    assert fn is not None, "write_ring_observe_drafts is the G2.2 batch entry"
    return fn(**kwargs)


def _subgraph() -> dict:
    return {
        "nodes": [
            {"id": "a", "role": "buyer"},
            {"id": "b", "role": "device"},
            {"id": "c", "role": "seller"},
        ],
        "edges": [
            {"src": "a", "dst": "b", "type": "USES_DEVICE"},
            {"src": "a", "dst": "c", "type": "TRANSACTED"},
        ],
    }


def _labels() -> list[dict]:
    return [
        {"entity_id": "a", "y_label": "1"},
        {"entity_id": "c", "y_label": "0"},
    ]


def _request(**extra) -> dict:
    body = {
        "schema_id": JOB_REQUEST_SCHEMA,
        "tenant_id": "t1",
        "subgraph": _subgraph(),
        "labels": _labels(),
    }
    body.update(extra)
    return body


def _live_pack() -> dict:
    return {
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


def test_g21_tags_mint_observe_shadow_live_packs_unchanged() -> None:
    live = _live_pack()
    before = deepcopy(live)
    job = run_ring_job(_request())
    assert job["live"] is False
    assert job["tags"]
    minted = write_ring_observe_drafts(packs=[live], request=_request())
    assert minted
    pack = minted[0]
    assert pack["mode"] == "shadow"
    assert pack["mode"] != "active"
    assert pack["lifecycle"]["state"] == "observe"
    assert pack["authored_by"] == "seed"
    assert pack["is_ai_authored"] is False
    eid = str(job["tags"][0]["entity_id"])
    assert pack["source_key"] == f"hil:ring:{eid}"
    assert (pack.get("evidence") or {}).get("hil_event_id") == f"ring:{eid}"
    assert live == before
    assert live["mode"] == "active"
    assert live["lifecycle"]["state"] == "promoted"


def test_evaluate_live_path_unchanged() -> None:
    paths = list(_EVALUATE_DIR.glob("*.py"))
    paths.append(Path(__file__).resolve().parents[1] / "src/decision_api/eval_steps.py")
    paths.append(Path(__file__).resolve().parents[1] / "src/decision_api/eval_dag.py")
    paths.append(Path(__file__).resolve().parents[1] / "src/decision_api/main.py")
    assert paths
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for needle in _WRITER_NEEDLES:
            assert needle not in text, f"{path.name} must not call ring writer"


def test_writer_never_sets_promoted_or_active() -> None:
    src = Path(ring_job.__file__).read_text(encoding="utf-8")
    for banned in _BANNED_WRITER:
        assert banned not in src, banned
    minted = write_ring_observe_drafts(packs=[], request=_request())
    assert minted
    for pack in minted:
        assert pack["mode"] == "shadow"
        assert pack["mode"] != "active"
        assert pack["lifecycle"]["state"] == "observe"
        assert pack["lifecycle"]["state"] != "promoted"
        blob = str(pack).upper()
        assert "FLAG" not in blob
        assert "DENY" not in blob
        assert "ALLOW" not in blob


def test_second_run_idempotent_hil_ring() -> None:
    first = write_ring_observe_drafts(packs=[], request=_request())
    assert first
    assert first[0]["source_key"].startswith("hil:ring:")
    second = write_ring_observe_drafts(packs=first, request=_request())
    assert second == []


def test_empty_tags_mint_no_drafts() -> None:
    req = {
        "schema_id": JOB_REQUEST_SCHEMA,
        "tenant_id": "t1",
        "edges": [{"src": "solo-a", "dst": "solo-b"}],
    }
    job = run_ring_job(req)
    assert job["tags"] == []
    assert write_ring_observe_drafts(packs=[], request=req) == []


def test_claim_lock_not_gnn_live_not_identity_sku() -> None:
    root = Path(__file__).resolve().parents[3]
    lock = (root / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
    planes = (root / "docs/contracts/graph-planes-v1.md").read_text(encoding="utf-8")
    blob = f"{lock}\n{planes}"
    assert "Observe" in blob
    assert "mode=shadow" in blob or "mode=shadow" in planes
    assert "authored_by=seed" in blob or "authored_by=seed" in planes
    assert "Not GNN live" in lock or "Not “GNN live”" in planes
    assert "Identity-as-SKU" in lock
    assert "auto active" in lock.lower() or "never auto active" in blob.lower()
    assert "GNN live" in lock
    low = blob.lower()
    assert "identity-as-sku" in low
    assert "gnn live" in low
