"""G2.4 — CI hard-locks: GNN unset; no auto live FLAG; no identity SKU."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from decision_api.pack_evaluator import _iter_eligible_packs, evaluate_packs_python
from decision_api.ring_job import JOB_REQUEST_SCHEMA, run_ring_job, write_ring_observe_drafts
from decision_api.ring_score import compute_ring_score

_ROOT = Path(__file__).resolve().parents[3]
_RULES = Path(__file__).resolve().parents[1] / "rules"
_CLAIM = _ROOT / "docs" / "compliance" / "CLAIM_LOCK.md"
_PLANES = _ROOT / "docs" / "contracts" / "graph-planes-v1.md"
_EVALUATE = Path(__file__).resolve().parents[1] / "src" / "decision_api" / "evaluate"
_HOP_PACKS = (
    "graph_v1_uses_device_v1.json",
    "graph_v1_has_instrument_v1.json",
    "graph_v1_has_list_v1.json",
)
_BANNED_EVAL = (
    "GRAPH_GNN_BETA_URL",
    "gnn_loop.serve",
    "score_graph_risk_beta",
    "run_ring_job",
    "write_ring_observe_drafts",
    "observe_drafts_from_ring",
)
_BANNED_AFFIRM = (
    "gnn is live",
    "gnn live by default",
    "gnn live scoring",
    "live gnn decision",
    "identity product sku",
    "identity as a sku",
    "identity-as-sku product",
    "ships identity-as-sku",
    "identity-as-sku is available",
)
_BUYER = (
    "README.md",
    "docs/INDEX.md",
    "docs/docs/index.md",
    "docs/docs/quickstart.md",
    "docs/docs/guides/clone-demo.md",
    "docs/docs/guides/product-day1-install.md",
    "docs/docs/guides/hop-pack-authoring.md",
    "docs/docs/guides/gnn-label-loop.md",
    "docs/docs/guides/graph-analysis.md",
    "docs/docs/guides/feature-data-flows.md",
    "docs/docs/guides/oss-15-minute-first-decision.md",
    "docs/compliance/CLAIM_LOCK.md",
    "docs/contracts/graph-planes-v1.md",
    "frontend/src/components/GraphRiskChallengerStrip.tsx",
    "frontend/src/components/GraphRiskChallengerPanel.tsx",
    "frontend/src/pages/Help.tsx",
    "frontend/src/pages/Settings.tsx",
)


def _tip_rows(lock: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    in_table = False
    for line in lock.splitlines():
        if line.startswith("| True on tip"):
            in_table = True
            continue
        if in_table and line.startswith("|") and "---" not in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 2:
                rows.append((parts[0], parts[1]))
        elif in_table and not line.startswith("|"):
            break
    return rows


def _ring_request() -> dict:
    return {
        "schema_id": JOB_REQUEST_SCHEMA,
        "tenant_id": "t1",
        "subgraph": {
            "nodes": [
                {"id": "a", "role": "buyer"},
                {"id": "b", "role": "device"},
                {"id": "c", "role": "seller"},
            ],
            "edges": [
                {"src": "a", "dst": "b", "type": "USES_DEVICE"},
                {"src": "a", "dst": "c", "type": "TRANSACTED"},
            ],
        },
        "labels": [
            {"entity_id": "a", "y_label": "1"},
            {"entity_id": "c", "y_label": "0"},
        ],
    }


def test_unset_gnn_beta_url_no_live_score_evaluate_stays_heuristic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GRAPH_GNN_BETA_URL", raising=False)
    assert os.environ.get("GRAPH_GNN_BETA_URL", "").strip() == ""

    from decision_api.gnn_loop.readiness import compute_graph_risk_readiness

    ready = compute_graph_risk_readiness(
        tenant_id="acme",
        receipts=[],
        labeled_rows=[],
        graph_service_url="",
        graph_gnn_beta_url=os.environ.get("GRAPH_GNN_BETA_URL", ""),
        gate=None,
    )
    assert ready["gnn_claim_allowed"] is False
    assert ready["overlay_url"] == "empty"
    assert ready["state"] != "live"
    assert "GNN live" not in str(ready)

    ring = compute_ring_score(
        metadata={
            "party_graph": {
                "nodes": [
                    {"id": "b1", "role": "buyer"},
                    {"id": "s1", "role": "seller"},
                    {"id": "dev1", "role": "device"},
                ],
                "edges": [
                    {"src": "b1", "dst": "dev1", "type": "USES_DEVICE"},
                    {"src": "s1", "dst": "dev1", "type": "USES_DEVICE"},
                ],
            }
        }
    )
    assert ring is not None
    ev = ring.evidence()
    assert ev["method"] == "heuristic_v1"
    assert ev["gnn_claim_allowed"] is False


@pytest.mark.asyncio
async def test_unset_gnn_beta_url_serve_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decision_api.gnn_loop.serve import score_graph_risk

    monkeypatch.delenv("GRAPH_GNN_BETA_URL", raising=False)
    monkeypatch.setenv("GNN_LOOP_GATE_PATH", str(tmp_path / "missing-gate.json"))
    assert await score_graph_risk("t", "e1") is None


def test_compose_lite_helm_do_not_set_gnn_beta_url() -> None:
    deploy = _ROOT / "infra" / "deploy"
    paths = list(deploy.rglob("docker-compose*.yml"))
    paths.extend((deploy / "helm").rglob("*.yaml"))
    paths.append(deploy / "docker-compose.lite.yml")
    assert paths
    for path in paths:
        blob = path.read_text(encoding="utf-8")
        assert "GRAPH_GNN_BETA_URL" not in blob, path


def test_evaluate_path_has_no_live_gnn_or_ring_authority() -> None:
    paths = list(_EVALUATE.glob("*.py"))
    paths.append(Path(__file__).resolve().parents[1] / "src/decision_api/eval_steps.py")
    paths.append(Path(__file__).resolve().parents[1] / "src/decision_api/eval_dag.py")
    rust = _ROOT / "packages" / "tarka-rule-engine" / "src" / "pack_ffi.rs"
    assert rust.is_file()
    assert 'if exclude_shadow && mode == "shadow"' in rust.read_text(encoding="utf-8")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for needle in _BANNED_EVAL:
            assert needle not in text, f"{path.name} must not wire {needle}"


def test_shadow_hop_packs_never_emit_live_flag_or_deny() -> None:
    for name in _HOP_PACKS:
        pack = json.loads((_RULES / name).read_text(encoding="utf-8"))
        assert pack.get("mode") == "shadow", name
        tags = [
            str(t)
            for rule in pack.get("rules") or []
            if isinstance(rule, dict)
            for t in (rule.get("tags") or [])
        ]
        assert "FLAG" in tags, name
        assert _iter_eligible_packs([pack], exclude_shadow=True) == []
        out = evaluate_packs_python(
            [pack],
            {},
            [],
            "t1",
            "e1",
            "production",
            exclude_shadow=True,
        )
        live = {str(t).upper() for t in out["tags"]}
        assert "FLAG" not in live
        assert "DENY" not in live
        assert out["rule_hits"] == []


def test_ring_observe_drafts_stay_observe_live_false_no_flag() -> None:
    req = _ring_request()
    job = run_ring_job(req)
    assert job["live"] is False
    blob = str(job).upper()
    assert "FLAG" not in blob
    assert "DENY" not in blob
    minted = write_ring_observe_drafts(packs=[], request=req)
    assert minted
    for pack in minted:
        assert pack["mode"] == "shadow"
        assert pack["mode"] != "active"
        assert pack["lifecycle"]["state"] == "observe"
        assert pack["lifecycle"]["state"] != "promoted"
        assert pack["authored_by"] == "seed"
        packed = str(pack).upper()
        assert "FLAG" not in packed
        assert "DENY" not in packed


def test_product_copy_has_no_gnn_live_or_identity_sku_overclaims() -> None:
    for rel in _BUYER:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        low = text.lower()
        for i, line in enumerate(text.splitlines(), 1):
            ll = line.lower()
            cells = [p.strip() for p in line.split("|") if p.strip()]
            forbidden_cell = cells[-1].lower() if len(cells) >= 2 else ""
            for phrase in _BANNED_AFFIRM:
                if phrase not in ll:
                    continue
                if phrase in forbidden_cell:
                    continue
                if any(n in ll for n in ("never", "not ", "must not", "no ")):
                    continue
                raise AssertionError(f"{rel}:{i} overclaim {phrase!r}: {line}")
        for m in re.finditer(r"identity-as-sku|identity as a sku|identity product sku", low):
            line = text[max(0, text.lower().rfind("\n", 0, m.start()) + 1) :].split("\n", 1)[0]
            ll = line.lower()
            cells = [p.strip() for p in line.split("|") if p.strip()]
            allowed = (
                "must not" in ll
                or "not " in ll
                or "never" in ll
                or "no identity" in ll
                or (len(cells) >= 2 and any(p in cells[-1].lower() for p in ("identity-as-sku", "identity product sku")))
            )
            assert allowed, f"{rel} identity SKU overclaim: {line}"


def test_claim_lock_g24_both_sides() -> None:
    lock = _CLAIM.read_text(encoding="utf-8")
    planes = _PLANES.read_text(encoding="utf-8")
    rows = _tip_rows(lock)
    assert rows
    for true_side, false_side in rows:
        tl = true_side.lower()
        if "gnn live" in tl:
            assert "not gnn live" in tl or "never" in tl
        if "identity-as-sku" in tl:
            assert "no identity-as-sku" in tl or "not identity-as-sku" in tl
        assert false_side.strip()  # keep BOTH sides

    assert any(
        "GRAPH_GNN_BETA_URL" in t and "unset" in t.lower() for t, _ in rows
    )
    assert any("gnn live" in f.lower() for _, f in rows)
    assert any("identity-as-sku" in f.lower() for _, f in rows)
    assert any("mode=shadow" in t for t, _ in rows)
    assert any("never auto active" in t.lower() or "observe" in t.lower() for t, _ in rows)
    assert any(
        "G2.4 CI" in t and "GRAPH_GNN_BETA_URL" in t for t, _ in rows
    ), "G2.4 CI hard-lock row missing on CLAIM_LOCK true side"
    g24 = next(r for r in rows if "G2.4 CI" in r[0])
    fl = g24[1].lower()
    assert "gnn live" in fl
    assert "identity" in fl and "sku" in fl
    assert "flag" in fl
    assert "Never" in planes and "ALLOW/DENY/FLAG" in planes
    assert "Not “GNN live”" in planes or 'Not "GNN live"' in planes
    assert "identity sku" not in planes.lower()
    assert "mode=shadow" in planes
