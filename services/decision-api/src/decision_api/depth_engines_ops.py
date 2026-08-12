"""Ops posture for OSS depth engines — schemas, methods, LIVE claim honesty."""

from __future__ import annotations

from typing import Any

from decision_api import depth_fusion as _fuse
from decision_api import dispute_representment as _disp
from decision_api import ftid_intake_gate as _ftid
from decision_api import lifecycle_risk as _life
from decision_api import listing_risk as _listing
from decision_api import promo_economics as _promo
from decision_api import ring_score as _ring
from decision_api import seller_trajectory as _traj
from decision_api.depth_engines import DEPTH_EVIDENCE_KEYS

_ENGINE_META: tuple[tuple[str, str, str, str, str, bool], ...] = (
    (
        "lifecycle_risk",
        _life.SCHEMA_ID,
        _life.METHOD,
        "metadata.lifecycle.events[]",
        "lifecycle_risk_engine",
        False,
    ),
    (
        "ring_score",
        _ring.SCHEMA_ID,
        _ring.METHOD,
        "metadata.party_graph",
        "ring_score_engine",
        False,
    ),
    (
        "seller_trajectory",
        _traj.SCHEMA_ID,
        _traj.METHOD,
        "metadata.seller_trajectory.windows[]",
        "seller_trajectory_engine",
        False,
    ),
    (
        "ftid_intake_gate",
        _ftid.SCHEMA_ID,
        _ftid.METHOD,
        "metadata.ftid",
        "ftid_intake_gate_engine",
        False,
    ),
    (
        "promo_economics",
        _promo.SCHEMA_ID,
        _promo.METHOD,
        "metadata.promo_economics",
        "promo_economics_engine",
        False,
    ),
    (
        "dispute_representment",
        _disp.SCHEMA_ID,
        _disp.METHOD,
        "metadata.dispute_evidence",
        "dispute_representment_engine",
        False,
    ),
    (
        "listing_risk",
        _listing.SCHEMA_ID,
        _listing.METHOD,
        "metadata.listing_risk",
        "listing_risk_engine",
        False,
    ),
    (
        "depth_fusion",
        _fuse.SCHEMA_ID,
        _fuse.METHOD,
        "child depth evidence (gated co-occurrence)",
        "depth_fusion_engine",
        False,
    ),
)


def load_depth_engines_ops_posture() -> dict[str, Any]:
    """Fail-closed ops view: methods/schemas; never claim LIVE GNN/vendor depth."""
    engines = []
    for eid, schema, method, host_input, rule_hit, gnn in _ENGINE_META:
        engines.append(
            {
                "engine_id": eid,
                "schema_id": schema,
                "method": method,
                "host_input": host_input,
                "rule_hit": rule_hit,
                "gnn_claim_allowed": gnn,
                "live_claim_allowed": False,
            }
        )
    return {
        "schema_id": "tarka.depth_engines_ops/v1",
        "evidence_keys": list(DEPTH_EVIDENCE_KEYS),
        "engine_count": len(engines),
        "engines": engines,
        "honesty": {
            "live_amplifies_same_interfaces": True,
            "forged_live_forbidden": True,
            "note": "Depth engines are OSS heuristics; vendor LIVE feeds attach signals, not rewrite methods.",
        },
    }
