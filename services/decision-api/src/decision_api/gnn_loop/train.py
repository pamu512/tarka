"""Offline train + holdout gate vs heuristic_v1. Fail closed.

A 1-layer neighborhood aggregation + logistic regression is trained on
exported rows. Serve is allowed only when holdout AUC beats ring_score
heuristic_v1 on the same rows. This is not a claim that a GNN works.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from decision_api.gnn_loop import GATE_SCHEMA_ID
from decision_api.ring_score import compute_ring_score

_EDGE_TYPES = ("USES_DEVICE", "USED", "SEEN_AT", "TRANSACTED", "RELATED", "OTHER")


def snapshot_to_party_graph(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    snap = snapshot if isinstance(snapshot, Mapping) else {}
    nodes = []
    for v in snap.get("vertices") or []:
        if not isinstance(v, dict):
            continue
        nid = str(v.get("id") or "").strip()
        if not nid:
            continue
        nodes.append({"id": nid, "role": str(v.get("role") or v.get("kind") or "unknown")})
    edges = []
    for e in snap.get("edges") or []:
        if not isinstance(e, dict):
            continue
        src = str(e.get("src") or e.get("from_id") or "").strip()
        dst = str(e.get("dst") or e.get("to_id") or "").strip()
        et = str(e.get("type") or "").strip().upper() or "RELATED"
        if src and dst:
            edges.append({"src": src, "dst": dst, "type": et})
    return {"nodes": nodes, "edges": edges}


def heuristic_v1_score(snapshot: Mapping[str, Any] | None) -> float:
    party = snapshot_to_party_graph(snapshot)
    result = compute_ring_score(metadata={"party_graph": party})
    if result is None:
        return 0.0
    return float(result.score_0_100)


def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> float:
    pos = [s for s, y in zip(scores, labels, strict=False) if int(y) == 1]
    neg = [s for s, y in zip(scores, labels, strict=False) if int(y) == 0]
    if not pos or not neg:
        return 0.5
    greater = 0.0
    ties = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                greater += 1.0
            elif p == n:
                ties += 1.0
    return (greater + 0.5 * ties) / (len(pos) * len(neg))


def graph_features(snapshot: Mapping[str, Any] | None) -> list[float]:
    snap = snapshot if isinstance(snapshot, Mapping) else {}
    verts = [v for v in (snap.get("vertices") or []) if isinstance(v, dict)]
    edges = [e for e in (snap.get("edges") or []) if isinstance(e, dict)]
    n_user = sum(1 for v in verts if str(v.get("kind") or "") == "user")
    n_bridge = sum(1 for v in verts if str(v.get("kind") or "") == "bridge")
    counts = {t: 0.0 for t in _EDGE_TYPES}
    adj: dict[str, list[str]] = {}
    for e in edges:
        src = str(e.get("src") or e.get("from_id") or "")
        dst = str(e.get("dst") or e.get("to_id") or "")
        et = str(e.get("type") or "OTHER").upper()
        if et not in counts:
            et = "OTHER"
        counts[et] += 1.0
        if src and dst:
            adj.setdefault(src, []).append(dst)
            adj.setdefault(dst, []).append(src)
    kind = {str(v.get("id") or ""): str(v.get("kind") or "") for v in verts}
    # One message-passing step: mean neighbor-is-bridge for user nodes.
    user_bridge_msgs: list[float] = []
    for v in verts:
        if str(v.get("kind") or "") != "user":
            continue
        nbs = adj.get(str(v.get("id") or ""), [])
        if not nbs:
            user_bridge_msgs.append(0.0)
            continue
        user_bridge_msgs.append(
            sum(1.0 for n in nbs if kind.get(n) == "bridge") / len(nbs)
        )
    msg = sum(user_bridge_msgs) / len(user_bridge_msgs) if user_bridge_msgs else 0.0
    n_edges = float(len(edges))
    return [
        float(n_user),
        float(n_bridge),
        n_edges,
        *(counts[t] for t in _EDGE_TYPES),
        msg,
    ]


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def train_mp_logreg(
    rows: Sequence[Mapping[str, Any]],
    *,
    steps: int = 80,
    lr: float = 0.15,
    seed: int = 0,
) -> tuple[list[float], float]:
    rng = random.Random(seed)
    xs = [graph_features(r.get("subgraph_snapshot")) for r in rows]
    ys = [1.0 if str(r.get("y_label")) == "1" else 0.0 for r in rows]
    if not xs:
        return [], 0.0
    dim = len(xs[0])
    weights = [rng.uniform(-0.05, 0.05) for _ in range(dim)]
    bias = 0.0
    n = float(len(xs))
    for _ in range(max(1, steps)):
        grad_w = [0.0] * dim
        grad_b = 0.0
        for x, y in zip(xs, ys, strict=False):
            z = bias + sum(w * v for w, v in zip(weights, x, strict=False))
            err = _sigmoid(z) - y
            for i, v in enumerate(x):
                grad_w[i] += err * v
            grad_b += err
        weights = [w - lr * g / n for w, g in zip(weights, grad_w, strict=False)]
        bias -= lr * grad_b / n
    return weights, bias


def score_mp_logreg(
    snapshot: Mapping[str, Any] | None,
    weights: Sequence[float],
    bias: float,
) -> float:
    if not weights:
        return 0.0
    x = graph_features(snapshot)
    z = float(bias) + sum(w * v for w, v in zip(weights, x, strict=False))
    return 100.0 * _sigmoid(z)


def evaluate_holdout_gate(
    holdout_rows: Sequence[Mapping[str, Any]],
    model_scores: Sequence[float],
) -> dict[str, Any]:
    """Fail closed unless the model strictly beats heuristic_v1 AUC."""
    labels = [1 if str(r.get("y_label")) == "1" else 0 for r in holdout_rows]
    if len(holdout_rows) < 4 or len(model_scores) != len(holdout_rows):
        return {
            "schema_id": GATE_SCHEMA_ID,
            "serve_allowed": False,
            "beats_heuristic": False,
            "baseline": "heuristic_v1",
            "reason": "holdout_too_small_or_score_mismatch",
            "model_auc": 0.5,
            "heuristic_auc": 0.5,
            "n_holdout": len(holdout_rows),
        }
    heur = [heuristic_v1_score(r.get("subgraph_snapshot")) for r in holdout_rows]
    model_auc = roc_auc(labels, list(model_scores))
    heur_auc = roc_auc(labels, heur)
    beats = model_auc > heur_auc
    return {
        "schema_id": GATE_SCHEMA_ID,
        "serve_allowed": bool(beats),
        "beats_heuristic": bool(beats),
        "baseline": "heuristic_v1",
        "reason": "ok" if beats else "holdout_did_not_beat_heuristic_v1",
        "model_auc": round(model_auc, 6),
        "heuristic_auc": round(heur_auc, 6),
        "n_holdout": len(holdout_rows),
    }


def write_gate_artifact(path: Path, gate: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_id": GATE_SCHEMA_ID,
        "serve_allowed": bool(gate.get("serve_allowed")),
        "beats_heuristic": bool(gate.get("beats_heuristic")),
        "baseline": str(gate.get("baseline") or "heuristic_v1"),
        "reason": str(gate.get("reason") or ""),
        "model_auc": gate.get("model_auc"),
        "heuristic_auc": gate.get("heuristic_auc"),
        "n_holdout": gate.get("n_holdout"),
        "weights": list(gate.get("weights") or []),
        "bias": float(gate.get("bias") or 0.0),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def train_and_gate(
    rows: Sequence[Mapping[str, Any]],
    *,
    holdout_frac: float = 0.4,
    seed: int = 0,
) -> dict[str, Any]:
    trainable = [
        r
        for r in rows
        if str(r.get("y_label")) in {"0", "1"}
        and r.get("trainable") is not False
        and isinstance((r.get("subgraph_snapshot") or {}).get("edges"), list)
        and (r.get("subgraph_snapshot") or {}).get("edges")
    ]
    if len(trainable) < 8:
        return {
            "schema_id": GATE_SCHEMA_ID,
            "serve_allowed": False,
            "beats_heuristic": False,
            "baseline": "heuristic_v1",
            "reason": "not_enough_edged_labeled_rows",
            "model_auc": 0.5,
            "heuristic_auc": 0.5,
            "n_holdout": 0,
            "weights": [],
            "bias": 0.0,
        }
    rng = random.Random(seed)
    order = list(trainable)
    rng.shuffle(order)
    cut = max(4, int(len(order) * holdout_frac))
    holdout = order[:cut]
    train = order[cut:] or order[:cut]
    weights, bias = train_mp_logreg(train, seed=seed)
    scores = [score_mp_logreg(r.get("subgraph_snapshot"), weights, bias) for r in holdout]
    gate = evaluate_holdout_gate(holdout, scores)
    gate["weights"] = weights
    gate["bias"] = bias
    return gate


def load_gate_artifact(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None
