"""Observe pack — FLAG on signed HAS_LIST hops, not a score blob."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from graph_contract import reset_tenant_registry
from graph_pack_atoms import (
    attach_hop_to_features,
    hop_view_from_graph_meta,
    hop_view_from_snapshot,
    pack_why_from_hop,
)
from pydantic import TypeAdapter

from decision_api.ast_evaluator import evaluate_json_ast
from decision_api.ast_models import JsonAstNode
from decision_api.json_rules import evaluate_json_rules, get_shadow_packs, load_rules
from decision_api.rule_pack_validation import validate_rule_pack

_PACK_PATH = Path(__file__).resolve().parents[1] / "rules" / "graph_v1_has_list_v1.json"


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_tenant_registry()
    yield
    reset_tenant_registry()


def _pack(*, active: bool = True) -> dict:
    data = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    data["_source_file"] = _PACK_PATH.name
    if active:
        data["mode"] = "active"
    return data


def _install(pack: dict) -> None:
    import decision_api.json_rules as jr

    jr._cached_packs = [pack]


def _hop_blob(
    *, multi_id: bool = True, sibling: bool = False, etype: str = "HAS_LIST"
) -> dict:
    named = [{"from_id": "alice", "to_id": "list:NK-1", "type": etype}]
    if multi_id:
        named.append({"from_id": "bob", "to_id": "list:NK-1", "type": etype})
    vertices = [
        {"id": "alice", "vtype": "user", "kind": "user"},
        {"id": "list:NK-1", "vtype": "list", "kind": "bridge"},
    ]
    if multi_id or sibling:
        props = {"y_label": "1" if sibling else "0", "FLAG": sibling}
        vertices.insert(
            1,
            {"id": "bob", "vtype": "user", "kind": "user", "properties": props},
        )
    return {
        "named_edges": named,
        "multi_id_user_ids": ["bob"] if multi_id else [],
        "roles": ["member"],
        "sibling_y_labels": {"bob": "FLAG"} if sibling else {},
        "vertices": vertices,
        "edges": list(named),
    }


def _features(blob: dict, *, graph_url: str, degrade_tags=None) -> dict:
    hop = hop_view_from_graph_meta(
        blob,
        graph_url=graph_url,
        degrade_tags=list(degrade_tags or []),
        tenant_id="t1",
        subject_id="alice",
    )
    feats: dict = {"amount": 12}
    attach_hop_to_features(feats, hop)
    return feats


def _eval(feats: dict):
    return evaluate_json_rules(feats, [], tenant_id="t1", entity_id="alice")


def test_pack_is_observe_seed_and_validates():
    data = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    assert data.get("version") == 1
    assert data.get("mode") == "shadow"
    assert data.get("name") == "graph_v1_has_list_v1"
    assert validate_rule_pack(data) == []
    rule = data["rules"][0]
    assert rule["id"] == "has_list_multi_or_sibling"
    assert "FLAG" in (rule.get("tags") or [])


def test_observe_load_does_not_activate_pack(tmp_path, monkeypatch):
    dest = tmp_path / _PACK_PATH.name
    dest.write_text(_PACK_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("decision_api.json_rules.settings.rules_path", str(tmp_path))
    load_rules()
    shadow_files = {p.get("_source_file") for p in get_shadow_packs()}
    assert _PACK_PATH.name in shadow_files
    hits, tags, _, _ = _eval(_features(_hop_blob(), graph_url="http://graph.test"))
    assert hits == []
    assert "FLAG" not in tags


def test_list_plus_multi_id_flags():
    _install(_pack())
    hits, tags, _, files = _eval(
        _features(
            _hop_blob(multi_id=True, sibling=False), graph_url="http://graph.test"
        )
    )
    assert "has_list_multi_or_sibling" in hits
    assert "FLAG" in tags
    assert _PACK_PATH.name in files


def test_empty_url_and_graph_missing_do_not_fire():
    _install(_pack())
    hits, tags, delta, _ = _eval(_features(_hop_blob(), graph_url=""))
    assert hits == []
    assert "FLAG" not in tags
    assert delta == 0.0


def test_unsigned_etype_does_not_fire():
    _install(_pack())
    hits, tags, delta, _ = _eval(
        _features(
            _hop_blob(multi_id=True, etype="RELATED"), graph_url="http://graph.test"
        )
    )
    assert hits == []
    assert "FLAG" not in tags
    assert delta == 0.0


def test_replay_from_snapshot_matches_live():
    _install(_pack())
    live_blob = _hop_blob(multi_id=True, sibling=True)
    live_feats = _features(live_blob, graph_url="http://graph.test")
    live_hop = hop_view_from_graph_meta(
        live_blob, graph_url="http://graph.test", tenant_id="t1", subject_id="alice"
    )
    replayed = hop_view_from_snapshot(
        {"graph_hop_v1": live_hop, "pack_why": {"graph": pack_why_from_hop(live_hop)}},
        tenant_id="t1",
        subject_id="alice",
    )
    replay_feats: dict = {"amount": 12}
    attach_hop_to_features(replay_feats, replayed)
    live_hits, live_tags, _, _ = _eval(live_feats)
    replay_hits, replay_tags, _, _ = _eval(replay_feats)
    assert live_hits == replay_hits
    assert "FLAG" in live_tags
    assert live_tags == replay_tags
    node = TypeAdapter(JsonAstNode).validate_python(_pack()["rules"][0]["when_ast"])
    assert evaluate_json_ast(node, live_feats) is True
    assert evaluate_json_ast(node, replay_feats) is True


def test_sibling_prior_flag_alone_with_signed_etype_flags():
    _install(_pack())
    feats = _features(
        _hop_blob(multi_id=False, sibling=True), graph_url="http://graph.test"
    )
    assert feats["_graph_hop_v1"]["multi_id_user_ids"] == []
    hits, tags, _, _ = _eval(feats)
    assert "has_list_multi_or_sibling" in hits
    assert "FLAG" in tags
