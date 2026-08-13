# Persisted Node Risk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the existing entity-risk score (plus relation growth and peer-degree flags) on graph nodes, query it on subgraph (depth 1–5) and top-N, and pass those fields through to investigation-agent tools / AgentRun.

**Architecture:** Extract a shared Python scorer. `compute_entity_risk` gathers counters (including 1h/24h incident-edge growth and optional tenant p90). graph-service SETs `risk_*` / growth on the node. Live GET write-through + mutation 1-hop refresh (cap 50). Subgraph reads stored fields (null if never computed). Investigation tools already call `/v1/subgraph`; no new tool.

**Tech Stack:** FastAPI graph-service, Neo4j Cypher (Janus/AGE twins), pytest driver mocks, investigation-agent playbooks/personas.

## Global Constraints

- Decision-api / rules remain sole allow/deny. Stored scores are features, not decisions.
- AI / Shadow never write `risk_*` properties.
- Do not invent scores when the graph backend is down.
- `0` is a real computed score. Unscored subgraph/top-N never use `0`.
- GET `/v1/analytics/entity-risk` for missing entity stays `risk_score: 0` + `entity_not_found` (add `scored: false`).
- Edges without `observed_at` / `created_at` / `updated_at` count toward degree only, not growth.
- Do not invent edge timestamps. New `create_link` without `observed_at` SETs now UTC.
- Query depth clamp 1–5. Do **not** recompute a 5-hop neighborhood on writes (1-hop persist, cap 50).
- Chat must not fetch a 5-hop subgraph on every turn.
- No PageRank/GDS. No Graph Explorer UI. No new investigation tool.
- `subgraph_with_velocity` transaction overlay stays. Graph growth is separate node fields.
- No live Neo4j required for unit tests (mock driver, same as `test_algorithms.py`).
- CI: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest …`
- Investigation tests: `cd services/investigation-agent && PYTHONPATH=src:../shared:../../packages/shared-core:../collaboration-chat-bridge/src pytest …`

## File map

| File | Responsibility |
|------|----------------|
| `services/graph-service/src/graph_service/entity_risk_score.py` | **Create.** Pure scoring, not-found payload, stored-field view, p90, persist eligibility |
| `services/graph-service/src/graph_service/entity_risk_writeback.py` | **Create.** `persist_entity_risk`, `refresh_touched_and_neighbors`, tenant refresh orchestration |
| `services/graph-service/src/graph_service/algorithms_neo4j.py` | Cypher growth counters; call shared scorer + peer p90 |
| `services/graph-service/src/graph_service/algorithms_janus.py` | Same counters/scorer on Gremlin |
| `services/graph-service/src/graph_service/algorithms_age.py` | Same counters/scorer |
| `services/graph-service/src/graph_service/neo4j_client.py` | `observed_at` on link; SET persist; 1-hop ids; subgraph decorate; top-N; GraphRiskStats |
| `services/graph-service/src/graph_service/janusgraph_store.py` | Same persist/query helpers |
| `services/graph-service/src/graph_service/age_client.py` | Same persist/query helpers |
| `services/graph-service/src/graph_service/graph_runtime.py` | Dispatch persist / 1-hop / top / stats (neo4j, janus, age) |
| `services/graph-service/src/graph_service/schemas.py` | `scored` + growth fields on `EntityRiskResponse` |
| `services/graph-service/src/graph_service/main.py` | Write-through GET; mutation refresh; top + refresh HTTP |
| `services/investigation-agent/src/investigation_agent/playbooks.py` | One line: depth up to 5, cite `fast_growth_*` / `high_degree_vs_peers` |
| `services/investigation-agent/src/investigation_agent/personas.py` | Same cite rule in workflow |
| `services/investigation-agent/src/investigation_agent/tools.py` | Tool description: graph node risk/growth fields, depth 1–5 |
| `contracts/openapi/graph-service.yaml` | Schema + top/refresh paths |
| `docs/docs/services/graph-service.md` | Formula + new endpoints |
| `docs/docs/api-reference.md` | New routes |

---

### Task 1: Shared scorer (growth + peer degree)

**Files:**
- Create: `services/graph-service/src/graph_service/entity_risk_score.py`
- Modify: `services/graph-service/src/graph_service/algorithms_neo4j.py` (call scorer; keep Cypher as-is until Task 2 — pass `relation_growth_*=0`, `peer_p90=None` via `.get`)
- Test: `services/graph-service/tests/test_entity_risk_score.py`

**Interfaces:**
- Consumes: existing factor math (tags +30, flagged min(n*10,25), community 15/8, shared devices min(n*10,20))
- Produces:
  - `FAST_GROWTH_1H = 5`, `FAST_GROWTH_24H = 15`
  - `entity_not_found_payload(entity_id, checkpoint, profile, hop_depth) -> dict`
  - `score_entity_risk(*, entity_id, tags, conn_count, flagged, community_size, shared_devices, neighbor_device_count, relation_growth_1h, relation_growth_24h, peer_p90, checkpoint, profile, hop_depth, freshness) -> dict`
  - `is_found_payload(payload) -> bool` (`"entity_not_found"` not in factors)
  - `stored_risk_view(props: dict) -> dict` (nulls when `risk_computed_at` missing)
  - `p90_degree(values: list[int]) -> int | None`

- [ ] **Step 1: Write the failing tests**

Create `services/graph-service/tests/test_entity_risk_score.py`:

```python
from graph_service.entity_risk_score import (
    entity_not_found_payload,
    p90_degree,
    score_entity_risk,
    stored_risk_view,
)


def _base(**over):
    kw = dict(
        entity_id="u1",
        tags=[],
        conn_count=0,
        flagged=0,
        community_size=1,
        shared_devices=0,
        neighbor_device_count=0,
        relation_growth_1h=0,
        relation_growth_24h=0,
        peer_p90=None,
        checkpoint=None,
        profile="standard",
        hop_depth=3,
        freshness=None,
    )
    kw.update(over)
    return score_entity_risk(**kw)


def test_five_timestamped_edges_in_1h_flags_fast_growth():
    out = _base(relation_growth_1h=5)
    assert out["relation_growth_1h"] == 5
    assert any(x.startswith("fast_growth_1h:") for x in out["risk_factors"])
    assert out["risk_score"] >= 20
    assert out["scored"] is True


def test_untimestamped_growth_zero_does_not_flag():
    out = _base(conn_count=4, relation_growth_1h=0)
    assert out["risk_factors"] == []
    assert out["risk_score"] == 0
    assert out["scored"] is True


def test_high_degree_vs_peers_not_stacked_with_high_connectivity():
    out = _base(conn_count=12, peer_p90=8)
    factors = out["risk_factors"]
    assert any(x.startswith("high_degree_vs_peers:12:p90=8") for x in factors)
    assert not any(x.startswith("high_connectivity:") for x in factors)


def test_absolute_connectivity_when_no_peer_stats():
    out = _base(conn_count=12, peer_p90=None)
    assert any(x.startswith("high_connectivity:12") for x in out["risk_factors"])
    assert not any(x.startswith("high_degree_vs_peers:") for x in out["risk_factors"])


def test_not_found_payload_zero_score_unscored():
    out = entity_not_found_payload("missing", None, None, 3)
    assert out["risk_score"] == 0
    assert out["scored"] is False
    assert "entity_not_found" in out["risk_factors"]
    assert out["relation_count"] == 0
    assert out["relation_growth_1h"] == 0


def test_stored_view_unscored_is_null_not_zero():
    view = stored_risk_view({})
    assert view["scored"] is False
    assert view["risk_score"] is None
    assert view["relation_growth_1h"] is None


def test_stored_view_computed_zero_is_scored():
    view = stored_risk_view(
        {
            "risk_score": 0,
            "risk_computed_at": "2026-08-13T00:00:00Z",
            "relation_count": 2,
            "relation_growth_1h": 0,
            "relation_growth_24h": 0,
            "risk_factors": [],
        }
    )
    assert view["scored"] is True
    assert view["risk_score"] == 0


def test_p90_empty_is_none():
    assert p90_degree([]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_risk_score.py -v
```

Expected: FAIL `ModuleNotFoundError: entity_risk_score`

- [ ] **Step 3: Write minimal implementation**

Create `entity_risk_score.py`:

```python
from __future__ import annotations

import math
from typing import Any

FAST_GROWTH_1H = 5
FAST_GROWTH_24H = 15
_HIGH_RISK_TAGS = frozenset({"fraud", "suspicious", "flagged", "blocked", "chargedback"})


def p90_degree(values: list[int]) -> int | None:
    if not values:
        return None
    xs = sorted(int(v) for v in values)
    idx = max(0, math.ceil(0.9 * len(xs)) - 1)
    return xs[idx]


def entity_not_found_payload(
    entity_id: str,
    checkpoint: str | None,
    profile: str | None,
    hop_depth: int,
) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "risk_score": 0,
        "risk_factors": ["entity_not_found"],
        "connected_flagged_count": 0,
        "community_size": 0,
        "neighbor_device_count": 0,
        "graph_checkpoint": checkpoint,
        "graph_profile": profile,
        "graph_profile_max_neighbor_hops": hop_depth,
        "scored": False,
        "relation_count": 0,
        "relation_growth_1h": 0,
        "relation_growth_24h": 0,
    }


def is_found_payload(payload: dict[str, Any]) -> bool:
    factors = payload.get("risk_factors") or []
    return "entity_not_found" not in [str(x) for x in factors]


def stored_risk_view(props: dict[str, Any] | None) -> dict[str, Any]:
    p = props if isinstance(props, dict) else {}
    computed = p.get("risk_computed_at")
    if computed is None or str(computed).strip() == "":
        return {
            "scored": False,
            "risk_score": None,
            "risk_computed_at": None,
            "risk_factors": None,
            "relation_count": None,
            "relation_growth_1h": None,
            "relation_growth_24h": None,
        }
    def _num(key: str) -> float | int | None:
        try:
            return p[key]
        except KeyError:
            return None
    return {
        "scored": True,
        "risk_score": _num("risk_score"),
        "risk_computed_at": str(computed),
        "risk_factors": list(p.get("risk_factors") or []),
        "relation_count": _num("relation_count"),
        "relation_growth_1h": _num("relation_growth_1h"),
        "relation_growth_24h": _num("relation_growth_24h"),
    }


def score_entity_risk(
    *,
    entity_id: str,
    tags: list[str],
    conn_count: int,
    flagged: int,
    community_size: int,
    shared_devices: int,
    neighbor_device_count: int,
    relation_growth_1h: int,
    relation_growth_24h: int,
    peer_p90: int | None,
    checkpoint: str | None,
    profile: str | None,
    hop_depth: int,
    freshness: str | None,
    multiplier: float = 1.0,
) -> dict[str, Any]:
    score = 0.0
    factors: list[str] = []
    own_risky = _HIGH_RISK_TAGS & {str(t).lower() for t in tags}
    if own_risky:
        score += 30
        factors.append(f"own_tags:{','.join(sorted(own_risky))}")
    if flagged > 0:
        score += min(flagged * 10, 25)
        factors.append(f"connected_flagged:{flagged}")
    if community_size >= 5:
        score += 15
        factors.append(f"large_community:{community_size}")
    elif community_size >= 3:
        score += 8
        factors.append(f"medium_community:{community_size}")
    if shared_devices > 0:
        score += min(shared_devices * 10, 20)
        factors.append(f"shared_devices:{shared_devices}")
    if peer_p90 is not None and conn_count >= max(10, int(peer_p90)):
        score += 15
        factors.append(f"high_degree_vs_peers:{conn_count}:p90={int(peer_p90)}")
    elif conn_count >= 10:
        score += 10
        factors.append(f"high_connectivity:{conn_count}")
    elif conn_count >= 5:
        score += 5
        factors.append(f"moderate_connectivity:{conn_count}")
    if relation_growth_1h >= FAST_GROWTH_1H:
        score += 20
        factors.append(f"fast_growth_1h:{relation_growth_1h}")
    if relation_growth_24h >= FAST_GROWTH_24H:
        score += 15
        factors.append(f"fast_growth_24h:{relation_growth_24h}")
    score = min(round(score * float(multiplier)), 100)
    out: dict[str, Any] = {
        "entity_id": entity_id,
        "risk_score": score,
        "risk_factors": factors,
        "connected_flagged_count": flagged,
        "community_size": community_size,
        "neighbor_device_count": neighbor_device_count,
        "graph_checkpoint": checkpoint,
        "graph_profile": profile,
        "graph_profile_multiplier": float(multiplier),
        "graph_profile_max_neighbor_hops": hop_depth,
        "scored": True,
        "relation_count": int(conn_count),
        "relation_growth_1h": int(relation_growth_1h),
        "relation_growth_24h": int(relation_growth_24h),
    }
    if freshness:
        out["graph_data_as_of"] = freshness
    return out
```

Then replace the inline score block in `algorithms_neo4j.compute_entity_risk` (and the not-found return) with `score_entity_risk` / `entity_not_found_payload`. Pass `relation_growth_1h=int(rec.get("relation_growth_1h") or 0)` (0 until Task 2). Pass `peer_p90=None` until Task 2. Keep existing tests green: `test_clean_user` still 0; `test_entity_not_found` still 0 + `entity_not_found`.

Do the same replacement in `algorithms_janus.py` and `algorithms_age.py` scoring blocks (same kwargs, growth 0, peer None).

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_risk_score.py tests/test_algorithms.py -v
```

Expected: PASS (including existing `TestComputeEntityRisk`)

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/entity_risk_score.py \
  services/graph-service/src/graph_service/algorithms_neo4j.py \
  services/graph-service/src/graph_service/algorithms_janus.py \
  services/graph-service/src/graph_service/algorithms_age.py \
  services/graph-service/tests/test_entity_risk_score.py
git commit -m "$(cat <<'EOF'
Share entity-risk scoring so growth and peer flags have one formula.

EOF
)"
```

---

### Task 2: Count relation growth + load peer p90

**Files:**
- Modify: `services/graph-service/src/graph_service/algorithms_neo4j.py` (Cypher + `load_peer_p90`)
- Modify: `services/graph-service/src/graph_service/algorithms_janus.py` (edge timestamps in the existing `bothE` loop)
- Modify: `services/graph-service/src/graph_service/algorithms_age.py` (same Cypher idea as Neo4j)
- Modify: `services/graph-service/src/graph_service/neo4j_client.py` (`load_peer_p90_by_label`)
- Modify: `services/graph-service/src/graph_service/graph_runtime.py` (dispatch `load_peer_p90_by_label`)
- Test: `services/graph-service/tests/test_algorithms.py`

**Interfaces:**
- Consumes: `score_entity_risk` from Task 1
- Produces: `compute_entity_risk` returns `relation_growth_1h`, `relation_growth_24h`, `relation_count`; uses `peer_p90` for the node’s primary label when `GraphRiskStats` exists
- `graph_runtime.load_peer_p90_by_label(tenant_id: str, label: str) -> int | None`

Growth Cypher (add to the existing query’s RETURN; do not drop current fields):

```cypher
OPTIONAL MATCH (n)-[e]-()
WITH n, conn_count, flagged_neighbors, community_size, shared_device_count, neighbor_device_count,
     e,
     coalesce(e.observed_at, e.created_at, e.updated_at) AS ts
WITH n, conn_count, flagged_neighbors, community_size, shared_device_count, neighbor_device_count,
     sum(CASE WHEN ts IS NOT NULL AND datetime(ts) >= datetime() - duration('PT1H') THEN 1 ELSE 0 END) AS relation_growth_1h,
     sum(CASE WHEN ts IS NOT NULL AND datetime(ts) >= datetime() - duration('PT24H') THEN 1 ELSE 0 END) AS relation_growth_24h
RETURN
  n.tags AS tags,
  n.updated_at AS updated_at,
  n.last_seen AS last_seen,
  n.tags_updated_at AS tags_updated_at,
  labels(n)[0] AS primary_label,
  conn_count,
  flagged_neighbors,
  community_size,
  shared_device_count,
  neighbor_device_count,
  relation_growth_1h,
  relation_growth_24h
```

If Neo4j `datetime(ts)` fails on ISO strings, count in Python: return `collect(ts)` of incident edge timestamps and count windows in Python with `datetime.fromisoformat`. Prefer Python counting if the mock driver cannot run `duration()`. **For unit tests**, the mock record already supplies `relation_growth_1h` / `relation_growth_24h` / `primary_label` — Cypher only matters live. Implement Python-side counting when the record has `edge_timestamps: list` **or** the two growth ints.

Janus: for each incident edge, read `observed_at` then `created_at` then `updated_at`; parse ISO; count 1h/24h. Untimestamped: skip growth, still in `conn_count`.

`load_peer_p90_by_label`:

```cypher
MATCH (s:GraphRiskStats {tenant_id: $tenant_id})
RETURN s.p90_degree_by_label AS raw
```

Parse JSON object; `raw.get(label)`. Missing node → `None`. Swallow errors → `None`.

- [ ] **Step 1: Write the failing tests**

Add this helper next to `_mock_record` in `test_algorithms.py`, then the two tests:

```python
def _driver_for_record(record):
    mock_result = AsyncMock()
    mock_result.single = AsyncMock(return_value=record)
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_driver = AsyncMock()
    mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_driver


class TestComputeEntityRisk:
    @pytest.mark.asyncio
    async def test_fast_growth_1h_from_record(self):
        record = _mock_record(
            {
                "tags": [],
                "conn_count": 5,
                "flagged_neighbors": 0,
                "community_size": 1,
                "shared_device_count": 0,
                "neighbor_device_count": 0,
                "relation_growth_1h": 5,
                "relation_growth_24h": 5,
                "primary_label": "Account",
            }
        )
        with patch(
            "graph_service.algorithms_neo4j.get_driver",
            AsyncMock(return_value=_driver_for_record(record)),
        ):
            result = await compute_entity_risk("tenant1", "burst-user")
        assert result["relation_growth_1h"] == 5
        assert any(x.startswith("fast_growth_1h:5") for x in result["risk_factors"])
        assert result["risk_score"] >= 20

    @pytest.mark.asyncio
    async def test_peer_p90_replaces_high_connectivity(self, monkeypatch):
        record = _mock_record(
            {
                "tags": [],
                "conn_count": 12,
                "flagged_neighbors": 0,
                "community_size": 1,
                "shared_device_count": 0,
                "neighbor_device_count": 0,
                "relation_growth_1h": 0,
                "relation_growth_24h": 0,
                "primary_label": "Account",
            }
        )
        monkeypatch.setattr(
            "graph_service.algorithms_neo4j.load_peer_p90_for_label",
            AsyncMock(return_value=8),
        )
        with patch(
            "graph_service.algorithms_neo4j.get_driver",
            AsyncMock(return_value=_driver_for_record(record)),
        ):
            result = await compute_entity_risk("tenant1", "hub")
        assert any(x.startswith("high_degree_vs_peers:12:p90=8") for x in result["risk_factors"])
        assert not any(x.startswith("high_connectivity:") for x in result["risk_factors"])
```

(Define `load_peer_p90_for_label` in `algorithms_neo4j.py` as a thin async wrapper so tests can patch it. Janus/AGE get the same name in those modules or import from `graph_runtime`.)

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_algorithms.py::TestComputeEntityRisk::test_fast_growth_1h_from_record tests/test_algorithms.py::TestComputeEntityRisk::test_peer_p90_replaces_high_connectivity -v
```

Expected: FAIL (missing keys / no `fast_growth_1h` / still `high_connectivity`)

- [ ] **Step 3: Write minimal implementation**

Wire Cypher/Gremlin counters into `score_entity_risk`. Add `async def load_peer_p90_for_label(tenant_id, label) -> int | None` that calls `graph_runtime`. Default growth ints to 0 when the mock omits them so old tests still pass.

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_algorithms.py tests/test_entity_risk_score.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/algorithms_neo4j.py \
  services/graph-service/src/graph_service/algorithms_janus.py \
  services/graph-service/src/graph_service/algorithms_age.py \
  services/graph-service/src/graph_service/neo4j_client.py \
  services/graph-service/src/graph_service/janusgraph_store.py \
  services/graph-service/src/graph_service/age_client.py \
  services/graph-service/src/graph_service/graph_runtime.py \
  services/graph-service/tests/test_algorithms.py
git commit -m "$(cat <<'EOF'
Count 1h/24h edge growth and apply peer-degree p90 when stats exist.

EOF
)"
```

---

### Task 3: Persist helper + GET write-through

**Files:**
- Create: `services/graph-service/src/graph_service/entity_risk_writeback.py`
- Modify: `services/graph-service/src/graph_service/schemas.py`
- Modify: `services/graph-service/src/graph_service/main.py` (`entity_risk_endpoint`)
- Modify: `services/graph-service/src/graph_service/neo4j_client.py` (`set_entity_risk_properties`)
- Modify: Janus/AGE stores + `graph_runtime.set_entity_risk_properties`
- Modify: `services/graph-service/tests/test_entity_risk_schema.py`
- Test: `services/graph-service/tests/test_entity_risk_writeback.py`

**Interfaces:**
- Consumes: `is_found_payload`, `compute_entity_risk`
- Produces:
  - `async def persist_entity_risk(tenant_id: str, entity_id: str, payload: dict) -> None`
  - SET only if `is_found_payload`; never CREATE
  - Properties: `risk_score`, `risk_factors`, `risk_computed_at` (UTC ISO Z), `relation_count`, `relation_growth_1h`, `relation_growth_24h`
  - Swallow SET errors (log)
  - GET found → persist **returned** payload after GNN-beta merge; growth fields stay from compute (beta must not invent them — copy from `base` before overwriting score)

- [ ] **Step 1: Write the failing tests**

`test_entity_risk_writeback.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from graph_service.entity_risk_score import entity_not_found_payload
from graph_service.entity_risk_writeback import persist_entity_risk


@pytest.mark.asyncio
async def test_persist_skips_not_found():
    setter = AsyncMock()
    with patch("graph_service.entity_risk_writeback.set_entity_risk_properties", setter):
        await persist_entity_risk("t", "missing", entity_not_found_payload("missing", None, None, 3))
    setter.assert_not_called()


@pytest.mark.asyncio
async def test_persist_sets_found_payload():
    setter = AsyncMock()
    payload = {
        "entity_id": "u1",
        "risk_score": 20,
        "risk_factors": ["fast_growth_1h:5"],
        "relation_count": 5,
        "relation_growth_1h": 5,
        "relation_growth_24h": 5,
        "scored": True,
    }
    with patch("graph_service.entity_risk_writeback.set_entity_risk_properties", setter):
        await persist_entity_risk("t", "u1", payload)
    setter.assert_awaited()
    kwargs = setter.await_args.kwargs if setter.await_args.kwargs else {}
    # positional: tenant_id, entity_id, props
    props = setter.await_args.args[2]
    assert props["risk_score"] == 20
    assert props["relation_growth_1h"] == 5
    assert "risk_computed_at" in props
```

`test_entity_risk_schema.py` — validate `scored` + growth fields.

HTTP write-through (`test_entity_risk_http.py` or same file) using FastAPI TestClient + patch `compute_entity_risk` and `persist_entity_risk`:

```python
def test_get_entity_risk_write_through_found(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    async def _compute(tenant_id, entity_id, checkpoint=None):
        return {"entity_id": entity_id, "risk_score": 20, "risk_factors": ["fast_growth_1h:5"],
                "connected_flagged_count": 0, "community_size": 1, "neighbor_device_count": 0,
                "scored": True, "relation_count": 5, "relation_growth_1h": 5, "relation_growth_24h": 5}
    persist = AsyncMock()
    monkeypatch.setattr("graph_service.main.compute_entity_risk", _compute)
    monkeypatch.setattr("graph_service.main.persist_entity_risk", persist)
    monkeypatch.setattr("graph_service.main.score_graph_risk_beta", AsyncMock(return_value=None))
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        r = client.get("/v1/analytics/entity-risk", params={"tenant_id": "t", "entity_id": "u1"})
    assert r.status_code == 200
    assert r.json()["scored"] is True
    persist.assert_awaited()


def test_get_entity_risk_not_found_does_not_persist(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    async def _compute(tenant_id, entity_id, checkpoint=None):
        from graph_service.entity_risk_score import entity_not_found_payload
        return entity_not_found_payload(entity_id, checkpoint, None, 3)

    persist = AsyncMock()
    monkeypatch.setattr("graph_service.main.compute_entity_risk", _compute)
    monkeypatch.setattr("graph_service.main.persist_entity_risk", persist)
    monkeypatch.setattr("graph_service.main.score_graph_risk_beta", AsyncMock(return_value=None))
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        r = client.get("/v1/analytics/entity-risk", params={"tenant_id": "t", "entity_id": "missing"})
    assert r.status_code == 200
    body = r.json()
    assert body["risk_score"] == 0
    assert body["scored"] is False
    persist.assert_not_awaited()
```

If TestClient import of `main` is heavy, patch at the same places `test_entity_deep_context_http.py` already does (`main.compute_entity_risk`).

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_risk_writeback.py tests/test_entity_risk_schema.py -v
```

Expected: FAIL import / `scored` missing

- [ ] **Step 3: Write minimal implementation**

`persist_entity_risk` in `entity_risk_writeback.py` imports `set_entity_risk_properties` from `graph_runtime`.

Neo4j SET:

```cypher
MATCH (n {tenant_id: $tenant_id, external_id: $entity_id})
SET n.risk_score = $risk_score,
    n.risk_factors = $risk_factors,
    n.risk_computed_at = $risk_computed_at,
    n.relation_count = $relation_count,
    n.relation_growth_1h = $relation_growth_1h,
    n.relation_growth_24h = $relation_growth_24h
```

No MERGE. 0 rows is fine.

`EntityRiskResponse` add:

```python
scored: bool = False
relation_count: int = Field(default=0, ge=0)
relation_growth_1h: int = Field(default=0, ge=0)
relation_growth_24h: int = Field(default=0, ge=0)
```

GET handler: after beta merge, `base["scored"] = is_found_payload(base)`; if scored, `await persist_entity_risk(...)` in try/except log. Persist failure must not 500.

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_risk_writeback.py tests/test_entity_risk_schema.py tests/test_algorithms.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/entity_risk_writeback.py \
  services/graph-service/src/graph_service/schemas.py \
  services/graph-service/src/graph_service/main.py \
  services/graph-service/src/graph_service/neo4j_client.py \
  services/graph-service/src/graph_service/janusgraph_store.py \
  services/graph-service/src/graph_service/age_client.py \
  services/graph-service/src/graph_service/graph_runtime.py \
  services/graph-service/tests/test_entity_risk_writeback.py \
  services/graph-service/tests/test_entity_risk_schema.py
git commit -m "$(cat <<'EOF'
Write through live entity-risk onto the node without creating missing entities.

EOF
)"
```

---

### Task 4: Link `observed_at` + mutation 1-hop refresh

**Files:**
- Modify: `services/graph-service/src/graph_service/neo4j_client.py` `create_link` (and Janus/AGE `create_link`)
- Modify: `services/graph-service/src/graph_service/entity_risk_writeback.py` (`refresh_touched_and_neighbors`, `MUTATION_REFRESH_CAP = 50`)
- Modify: `services/graph-service/src/graph_service/graph_runtime.py` (`list_one_hop_ids`)
- Modify: `services/graph-service/src/graph_service/main.py` (after successful upsert / tags / links)
- Test: `services/graph-service/tests/test_entity_risk_writeback.py`

**Interfaces:**
- Consumes: `persist_entity_risk`, `compute_entity_risk`
- Produces:
  - `create_link`: if `properties` has no `observed_at`, set ISO UTC now before SET. Do not backfill other edges.
  - `async def list_one_hop_ids(tenant_id: str, entity_id: str) -> list[str]`
  - `async def refresh_touched_and_neighbors(tenant_id: str, entity_ids: Sequence[str]) -> None`
  - Order: touched ids first, then neighbors; cap 50; each `compute_entity_risk` + `persist_entity_risk`; never raise
  - Upsert: refresh `[external_id]`; tags: `[external_id]`; link: `[from, to]`

- [ ] **Step 1: Write the failing tests**

```python
def test_create_link_adds_observed_at_when_missing():
    from graph_service.neo4j_client import _link_properties_with_observed_at
    props = _link_properties_with_observed_at({})
    assert "observed_at" in props
    kept = _link_properties_with_observed_at({"observed_at": "2020-01-01T00:00:00Z"})
    assert kept["observed_at"] == "2020-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_refresh_caps_at_50_and_puts_touched_first():
    hops = AsyncMock(side_effect=lambda t, e: [f"n{i}" for i in range(60)] if e == "a" else [])
    compute = AsyncMock(return_value={"entity_id": "x", "risk_factors": [], "risk_score": 0, "relation_count": 0, "relation_growth_1h": 0, "relation_growth_24h": 0})
    persist = AsyncMock()
    with patch("graph_service.entity_risk_writeback.list_one_hop_ids", hops), \
         patch("graph_service.entity_risk_writeback.compute_entity_risk", compute), \
         patch("graph_service.entity_risk_writeback.persist_entity_risk", persist):
        from graph_service.entity_risk_writeback import refresh_touched_and_neighbors
        await refresh_touched_and_neighbors("t", ["a", "b"])
    assert persist.await_count == 50
    first = persist.await_args_list[0].args[1]
    second = persist.await_args_list[1].args[1]
    assert first == "a" and second == "b"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_risk_writeback.py -v
```

Expected: FAIL missing helpers

- [ ] **Step 3: Write minimal implementation**

`_link_properties_with_observed_at` in `neo4j_client.py` (Janus/AGE call the same helper from `entity_risk_score.py` or writeback to avoid three copies — put it in `entity_risk_score.py`).

`list_one_hop_ids` Cypher:

```cypher
MATCH (n {tenant_id: $tenant_id, external_id: $entity_id})-[r]-(m)
WHERE m.tenant_id = $tenant_id
RETURN collect(DISTINCT m.external_id) AS ids
```

`main.py`: after successful upsert/tags/link, `asyncio.create_task` is **not** required; `await refresh_touched_and_neighbors(...)` inside try/except so the HTTP still 200. Keep it sequential and best-effort.

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_risk_writeback.py tests/test_algorithms.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/entity_risk_writeback.py \
  services/graph-service/src/graph_service/entity_risk_score.py \
  services/graph-service/src/graph_service/neo4j_client.py \
  services/graph-service/src/graph_service/janusgraph_store.py \
  services/graph-service/src/graph_service/age_client.py \
  services/graph-service/src/graph_service/graph_runtime.py \
  services/graph-service/src/graph_service/main.py \
  services/graph-service/tests/test_entity_risk_writeback.py
git commit -m "$(cat <<'EOF'
Stamp new links with observed_at and refresh node plus 1-hop risk.

EOF
)"
```

---

### Task 5: Subgraph and deep-context stored fields

**Files:**
- Modify: `services/graph-service/src/graph_service/neo4j_client.py` `_node_to_dict` (and Janus/AGE node dict builders)
- Test: `services/graph-service/tests/test_entity_risk_score.py` (view already) + `services/graph-service/tests/test_subgraph_risk_fields.py`

**Interfaces:**
- Consumes: `stored_risk_view`
- Produces: each subgraph node top-level `scored`, `risk_score` (`number|null`), `risk_computed_at`, `risk_factors`, `relation_count`, `relation_growth_1h`, `relation_growth_24h`. Do **not** call `compute_entity_risk` per node. Depth still `max(1, min(depth, 5))`.

- [ ] **Step 1: Write the failing tests**

```python
from graph_service.entity_risk_score import decorate_subgraph_node


def test_decorate_unscored_nulls():
    node = {"id": "u1", "labels": ["Account"], "properties": {"external_id": "u1"}}
    out = decorate_subgraph_node(node)
    assert out["scored"] is False
    assert out["risk_score"] is None


def test_decorate_scored_zero():
    node = {
        "id": "u1",
        "labels": ["Account"],
        "properties": {
            "risk_score": 0,
            "risk_computed_at": "2026-08-13T00:00:00Z",
            "relation_count": 1,
            "relation_growth_1h": 0,
            "relation_growth_24h": 0,
            "risk_factors": [],
        },
    }
    out = decorate_subgraph_node(node)
    assert out["scored"] is True
    assert out["risk_score"] == 0
```

Add `_clamp_depth(6) == 5` already exists; add HTTP test only if TestClient is already used: patch `query_subgraph` to return an undecorated node and assert the endpoint returns decorated fields **or** decorate inside `query_subgraph` so the patch is unnecessary.

Prefer decorate inside `_node_to_dict` / Janus equivalent so all callers (subgraph, deep-context) get fields.

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_subgraph_risk_fields.py -v
```

Expected: FAIL missing `decorate_subgraph_node`

- [ ] **Step 3: Write minimal implementation**

```python
def decorate_subgraph_node(node: dict[str, Any]) -> dict[str, Any]:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    view = stored_risk_view(props)
    return {**node, **view}
```

Call from `_node_to_dict` before return.

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_subgraph_risk_fields.py tests/test_entity_deep_context_http.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/entity_risk_score.py \
  services/graph-service/src/graph_service/neo4j_client.py \
  services/graph-service/src/graph_service/janusgraph_store.py \
  services/graph-service/src/graph_service/age_client.py \
  services/graph-service/tests/test_subgraph_risk_fields.py
git commit -m "$(cat <<'EOF'
Expose stored node risk on subgraph reads without recomputing.

EOF
)"
```

---

### Task 6: Top-N + tenant/entity refresh + GraphRiskStats

**Files:**
- Modify: `services/graph-service/src/graph_service/neo4j_client.py` (`list_entity_risk_top`, `scan_tenant_entity_ids`, `upsert_graph_risk_stats`)
- Modify: `entity_risk_writeback.py` (`refresh_entity`, `refresh_tenant`)
- Modify: `main.py` (two HTTP routes)
- Modify: `contracts/openapi/graph-service.yaml`
- Modify: `docs/docs/services/graph-service.md`, `docs/docs/api-reference.md`
- Test: `services/graph-service/tests/test_entity_risk_refresh_top.py`

**Interfaces:**
- `GET /v1/analytics/entity-risk/top?tenant_id=&limit=50&min_score=0`
  - `limit` clamp 1–200, `min_score` default 0
  - `WHERE n.risk_computed_at IS NOT NULL AND n.risk_score >= $min_score`
  - `ORDER BY n.risk_score DESC, n.external_id ASC`
  - `{ "entities": [ { entity_id, labels, risk_score, risk_factors, risk_computed_at, relation_count, relation_growth_1h, relation_growth_24h } ] }`
- `POST /v1/analytics/entity-risk/refresh` body `{ tenant_id, entity_id?, limit? }`
  - entity: 404 if compute not-found; else persist; `{updated:1, skipped:0, truncated:false}` (no p90 rewrite)
  - tenant: `limit` default 5000 clamp 1–20000; scan `ORDER BY external_id`; persist each found; `skipped` = not-found (should be 0 if scan is real nodes); `truncated` if more ids than limit; then `p90_degree` per primary label from **scanned** `relation_count` → MERGE `(:GraphRiskStats {tenant_id})` SET `p90_degree_by_label` JSON + `stats_computed_at`

- [ ] **Step 1: Write the failing tests**

```python
def _top_row(eid: str, score: float) -> dict:
    return {
        "entity_id": eid,
        "labels": ["Account"],
        "risk_score": score,
        "risk_factors": [],
        "risk_computed_at": "2026-08-13T00:00:00Z",
        "relation_count": 3,
        "relation_growth_1h": 0,
        "relation_growth_24h": 0,
    }


def test_top_returns_mock_order(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    rows = [_top_row("a", 90.0), _top_row("b", 40.0)]
    monkeypatch.setattr("graph_service.main.list_entity_risk_top", AsyncMock(return_value=rows))
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        data = client.get(
            "/v1/analytics/entity-risk/top",
            params={"tenant_id": "t", "limit": 10, "min_score": 0},
        ).json()
    assert [e["entity_id"] for e in data["entities"]] == ["a", "b"]


def test_limit_clamp():
    from graph_service.entity_risk_writeback import clamp_top_limit, clamp_refresh_limit
    assert clamp_top_limit(0) == 1
    assert clamp_top_limit(999) == 200
    assert clamp_refresh_limit(0) == 1
    assert clamp_refresh_limit(99999) == 20000


def test_refresh_entity_404(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    from graph_service.entity_risk_score import entity_not_found_payload
    monkeypatch.setattr(
        "graph_service.main.compute_entity_risk",
        AsyncMock(return_value=entity_not_found_payload("x", None, None, 3)),
    )
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        r = client.post("/v1/analytics/entity-risk/refresh", json={"tenant_id": "t", "entity_id": "x"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_refresh_tenant_truncated_writes_p90(monkeypatch):
    from graph_service.entity_risk_writeback import refresh_tenant

    found = {
        "risk_score": 10,
        "risk_factors": [],
        "relation_growth_1h": 0,
        "relation_growth_24h": 0,
        "scored": True,
        "primary_label": "Account",
    }
    monkeypatch.setattr(
        "graph_service.entity_risk_writeback.scan_tenant_entity_ids",
        AsyncMock(return_value=(["a", "b", "c"], True)),
    )
    monkeypatch.setattr(
        "graph_service.entity_risk_writeback.compute_entity_risk",
        AsyncMock(
            side_effect=lambda t, e, **k: {
                **found,
                "entity_id": e,
                "relation_count": 10 if e == "a" else 1,
            }
        ),
    )
    monkeypatch.setattr("graph_service.entity_risk_writeback.persist_entity_risk", AsyncMock())
    upsert = AsyncMock()
    monkeypatch.setattr("graph_service.entity_risk_writeback.upsert_graph_risk_stats", upsert)
    out = await refresh_tenant("t", limit=2)
    assert out["truncated"] is True
    upsert.assert_awaited()
```

Also assert `list_entity_risk_top` Cypher contains `risk_computed_at IS NOT NULL` (read the query string in `neo4j_client.py` or capture `session.run` args in a driver mock).

Also unit-test `list_entity_risk_top` mock session: records without `risk_computed_at` must not appear (if filtering is in Cypher, assert the query string contains `risk_computed_at IS NOT NULL`).

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_risk_refresh_top.py -v
```

Expected: FAIL missing routes/helpers

- [ ] **Step 3: Write minimal implementation**

Add routes in `main.py`. Auth: same as other analytics (no new role). 422 on missing `tenant_id` via FastAPI. Clamp, do not 400, for limit.

OpenAPI: add paths + `scored` / growth on `EntityRiskResponse`. Docs: formula table + top/refresh.

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/graph-service
PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/ -q
```

Expected: PASS (coverage floor 26 still)

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/entity_risk_writeback.py \
  services/graph-service/src/graph_service/neo4j_client.py \
  services/graph-service/src/graph_service/janusgraph_store.py \
  services/graph-service/src/graph_service/age_client.py \
  services/graph-service/src/graph_service/graph_runtime.py \
  services/graph-service/src/graph_service/main.py \
  services/graph-service/tests/test_entity_risk_refresh_top.py \
  contracts/openapi/graph-service.yaml \
  docs/docs/services/graph-service.md \
  docs/docs/api-reference.md
git commit -m "$(cat <<'EOF'
Add entity-risk top-N and refresh, including tenant peer p90 stats.

EOF
)"
```

---

### Task 7: Investigation-agent + AgentRun passthrough

**Files:**
- Modify: `services/investigation-agent/src/investigation_agent/playbooks.py` (`mule_layering` and `account_takeover` fragments — one sentence each)
- Modify: `services/investigation-agent/src/investigation_agent/personas.py` (`_WORKFLOW_AND_TAIL`)
- Modify: `services/investigation-agent/src/investigation_agent/tools.py` (`subgraph` + `subgraph_with_velocity` descriptions)
- Test: `services/investigation-agent/tests/test_agent.py`
- Test: `services/investigation-agent/tests/test_agent_run_and_context.py`

**Interfaces:**
- Consumes: subgraph JSON already returned by tools (Task 5 fields)
- Produces: no new tool; `_validate_depth(5)==5`, `_validate_depth(6)==5`; playbook/persona tell the model to use depth up to 5 and cite `fast_growth_1h`, `fast_growth_24h`, `high_degree_vs_peers` only when present; AgentRun stores `graph_neighborhood` as given (vertices may include `risk_score`)

Exact playbook sentence to append to `mule_layering` fragment (after the graph depth line):

`When checking rings, shared devices, or mule fan-out, call subgraph_with_velocity with depth up to 5 and cite node risk_factors (fast_growth_1h, fast_growth_24h, high_degree_vs_peers). Do not claim growth if those factors are absent.`

Persona workflow add after the subgraph_with_velocity bullet:

`- Graph nodes may include scored, risk_score, relation_growth_1h/24h, and risk_factors from graph-service. Cite fast_growth_* / high_degree_vs_peers only when present. You may pass depth up to 5; default stays 2. Do not fetch a 5-hop subgraph on every turn.`

Tool description add: `Each node may include scored, risk_score, relation_growth_1h, relation_growth_24h, risk_factors (graph relation growth — not the transaction velocity overlay). depth is clamped 1–5.`

- [ ] **Step 1: Write the failing tests**

```python
from investigation_agent.tools import _validate_depth

def test_validate_depth_allows_five_clamps_six():
    assert _validate_depth(5) == 5
    assert _validate_depth(6) == 5


@pytest.mark.asyncio
async def test_subgraph_tool_passes_through_node_risk(monkeypatch):
    http = AsyncMock()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "nodes": [{"id": "u1", "scored": True, "risk_score": 20, "risk_factors": ["fast_growth_1h:5"]}],
        "edges": [],
    }
    resp.raise_for_status = MagicMock()
    http.get = AsyncMock(return_value=resp)
    monkeypatch.setattr("investigation_agent.tools.settings.graph_service_url", "http://graph.test")
    monkeypatch.setattr("investigation_agent.tools._analyst_allowed", lambda a: True)
    from investigation_agent.tools import tool_subgraph
    out = await tool_subgraph(http, "u1", "t", "analyst1", depth=5)
    assert out["nodes"][0]["risk_score"] == 20
    http.get.assert_awaited()
    assert http.get.await_args.kwargs["params"]["depth"] == 5
```

AgentRun:

```python
def test_agent_run_keeps_neighborhood_risk_fields(data_dir: Path) -> None:
    from investigation_agent import agent_run_store
    from investigation_agent.context_assembler import assemble_context_snapshot
    snap = assemble_context_snapshot(
        tenant_id="ten-a",
        case_id="c9",
        case_payload={"id": "c9"},
        graph_neighborhood={"vertices": [{"id": "u1", "risk_score": 20, "risk_factors": ["fast_growth_1h:5"]}]},
    )
    rid = agent_run_store.persist_agent_run(
        turn_id="turn-1", tenant_id="ten-a", analyst_id="a", case_id="c9",
        context_snapshot=snap, source="chat",
    )
    got = agent_run_store.get_agent_run(run_id=rid, tenant_id="ten-a")
    verts = (got["context_snapshot"].get("graph_neighborhood") or got["context_snapshot"])
    # assert the snapshot still contains risk_score 20 on a vertex — walk artifacts/sources as assemble_context_snapshot actually stores them
```

Inspect `assemble_context_snapshot` return shape in `context_assembler.py` and assert on the real key (`sources` / `artifacts` excerpt). Do **not** add a subgraph HTTP call in chat.

Playbook test: `from investigation_agent.playbooks import playbook_system_append` (or `list_playbooks`) and `assert "fast_growth_1h" in fragment`.

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core:../collaboration-chat-bridge/src pytest tests/test_agent.py::test_subgraph_tool_passes_through_node_risk tests/test_agent.py::test_validate_depth_allows_five_clamps_six -v
```

Expected: FAIL (depth 5 tool test / missing copy)

- [ ] **Step 3: Write minimal implementation**

Playbook + persona + tool description only. No new endpoints. `_validate_depth` already clamps — the tool test should pass once descriptions exist if depth is already forwarded; if `tool_subgraph` already passes `depth`, only the playbook assert is RED until copy lands.

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/investigation-agent
PYTHONPATH=src:../shared:../../packages/shared-core:../collaboration-chat-bridge/src pytest tests/test_agent.py tests/test_agent_run_and_context.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/investigation-agent/src/investigation_agent/playbooks.py \
  services/investigation-agent/src/investigation_agent/personas.py \
  services/investigation-agent/src/investigation_agent/tools.py \
  services/investigation-agent/tests/test_agent.py \
  services/investigation-agent/tests/test_agent_run_and_context.py
git commit -m "$(cat <<'EOF'
Let investigation tools cite persisted graph growth risk up to 5 hops.

EOF
)"
```

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Shared formula + growth/peer points | 1–2 |
| GET `entity_not_found` stays 0 + `scored: false` | 1, 3 |
| Persist properties / no CREATE | 3 |
| GET write-through (post-beta score, compute growth) | 3 |
| `observed_at` on new links | 4 |
| Mutation 1-hop cap 50 | 4 |
| No 5-hop write refresh | 4 |
| Subgraph stored fields, depth 1–5 | 5 |
| Top-N | 6 |
| Refresh entity 404 / tenant cap / GraphRiskStats p90 | 6 |
| Janus/AGE same scorer + persist | 1–6 |
| AI tools/playbook/persona, no new tool, no per-turn 5-hop fetch | 7 |
| AgentRun passthrough | 7 |
| OpenAPI/docs | 6 |
