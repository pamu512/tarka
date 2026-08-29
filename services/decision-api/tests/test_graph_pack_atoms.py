"""graph_v1 when_ast — packs fire on the as-of hop, not a score blob."""

from __future__ import annotations

import pytest
from graph_contract import reset_tenant_registry
from graph_pack_atoms import (
    attach_hop_to_features,
    hop_view_from_graph_meta,
    hop_view_from_snapshot,
)
from pydantic import TypeAdapter, ValidationError

from decision_api.ast_evaluator import evaluate_json_ast
from decision_api.ast_models import EvaluateAstRequest, JsonAstNode
from decision_api.json_rules import evaluate_json_rules


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_tenant_registry()
    yield
    reset_tenant_registry()


_SHARED_DEVICE_FLAGGED = {
    "type": "and",
    "children": [
        {"type": "graph_v1", "atom": "has_etype", "etype": "USES_DEVICE"},
        {"type": "graph_v1", "atom": "has_multi_id"},
        {"type": "graph_v1", "atom": "sibling_prior_flag"},
    ],
}

_PACK = {
    "version": 1,
    "_source_file": "graph_v1_shared_device.json",
    "rules": [
        {
            "id": "shared_device_flagged_sibling",
            "when_ast": _SHARED_DEVICE_FLAGGED,
            "tags": ["graph:shared_device_flagged_sibling"],
            "score_delta": 18,
        }
    ],
    "tag_rules": [],
}


def _hop_blob(*, flagged: bool = True) -> dict:
    return {
        "named_edges": [
            {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"},
            {"from_id": "bob", "to_id": "dev-1", "type": "USES_DEVICE"},
        ],
        "multi_id_user_ids": ["bob"],
        "roles": ["member"],
        "sibling_y_labels": {"bob": "FLAG"} if flagged else {},
        "vertices": [
            {"id": "alice", "vtype": "user", "kind": "user"},
            {
                "id": "bob",
                "vtype": "user",
                "kind": "user",
                "properties": {"y_label": "1" if flagged else "0", "FLAG": flagged},
            },
            {"id": "dev-1", "vtype": "device", "kind": "bridge"},
        ],
        "edges": [
            {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"},
            {"from_id": "bob", "to_id": "dev-1", "type": "USES_DEVICE"},
        ],
    }


def _features_from_hop(blob: dict, *, graph_url: str, degrade_tags=None) -> dict:
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


def test_shared_device_flagged_sibling_pack_fires():
    import decision_api.json_rules as jr

    jr._cached_packs = [_PACK]
    hits, tags, delta, _ = evaluate_json_rules(
        _features_from_hop(_hop_blob(), graph_url="http://graph.test"),
        [],
        tenant_id="t1",
        entity_id="alice",
    )
    assert "shared_device_flagged_sibling" in hits
    assert "graph:shared_device_flagged_sibling" in tags
    assert delta >= 18


def test_empty_url_pack_does_not_fire():
    import decision_api.json_rules as jr

    jr._cached_packs = [_PACK]
    hits, tags, delta, _ = evaluate_json_rules(
        _features_from_hop(_hop_blob(), graph_url=""),
        [],
        tenant_id="t1",
        entity_id="alice",
    )
    assert hits == []
    assert "graph:shared_device_flagged_sibling" not in tags
    assert delta == 0.0


def test_unsigned_etype_refused_at_ast_parse():
    with pytest.raises(ValidationError):
        EvaluateAstRequest.model_validate(
            {
                "features": {},
                "ast": {"type": "graph_v1", "atom": "has_etype", "etype": "RELATED"},
            }
        )
    with pytest.raises(ValidationError):
        EvaluateAstRequest.model_validate(
            {
                "features": {},
                "ast": {
                    "type": "graph_v1",
                    "atom": "has_etype",
                    "etype": "not-a-token!",
                },
            }
        )


def test_unsigned_etype_in_pack_does_not_fire():
    import decision_api.json_rules as jr

    jr._cached_packs = [
        {
            "version": 1,
            "_source_file": "ghost.json",
            "rules": [
                {
                    "id": "ghost_etype",
                    "when_ast": {
                        "type": "graph_v1",
                        "atom": "has_etype",
                        "etype": "GHOST_EDGE",
                    },
                    "tags": ["should-not-fire"],
                    "score_delta": 50,
                }
            ],
            "tag_rules": [],
        }
    ]
    feats = _features_from_hop(
        {
            "named_edges": [
                {"from_id": "a", "to_id": "b", "type": "GHOST_EDGE"},
            ]
        },
        graph_url="http://graph.test",
    )
    hits, tags, delta, _ = evaluate_json_rules(feats, [], tenant_id="t1", entity_id="a")
    assert hits == []
    assert "should-not-fire" not in tags
    assert delta == 0.0


def test_replay_from_snapshot_matches_live_ast():
    live_blob = _hop_blob()
    live_feats = _features_from_hop(live_blob, graph_url="http://graph.test")
    replayed = hop_view_from_snapshot(
        {
            "subgraph_snapshot": {
                "status": "graph:ok",
                "tenant_id": "t1",
                "entity_id": "alice",
                "vertices": live_blob["vertices"],
                "edges": live_blob["edges"],
                "named_edges": live_blob["named_edges"],
                "multi_id_user_ids": live_blob["multi_id_user_ids"],
                "sibling_y_labels": live_blob["sibling_y_labels"],
            }
        },
        tenant_id="t1",
        subject_id="alice",
    )
    replay_feats: dict = {"amount": 12}
    attach_hop_to_features(replay_feats, replayed)
    node = TypeAdapter(JsonAstNode).validate_python(_SHARED_DEVICE_FLAGGED)
    assert evaluate_json_ast(node, live_feats) is True
    assert evaluate_json_ast(node, replay_feats) is True
    assert evaluate_json_ast(node, live_feats) == evaluate_json_ast(node, replay_feats)


def test_graph_v1_is_a_leaf_in_when_ast():
    raw = {"type": "graph_v1", "atom": "has_multi_id"}
    req = EvaluateAstRequest.model_validate(
        {
            "features": _features_from_hop(_hop_blob(), graph_url="http://graph.test"),
            "ast": raw,
        }
    )
    assert evaluate_json_ast(req.ast, req.features) is True
