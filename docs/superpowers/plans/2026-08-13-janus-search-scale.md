# Janus Search Scale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Janus typeahead uses a Lucene mixed-index prefix query (capped scan + `truncated` if the index is not ENABLED); owner hop and subgraph/deep-context stop doing one Gremlin round-trip per vertex.

**Architecture:** Shared Python prefix re-check and `(via, owner)` fan-out dedupe in `entity_risk_score.py`. HTTP search returns `{entities, truncated}`. Janus `Client.submit` Groovy ensures mixed index `vertexSearch` on backend `search` at first connect; search is a union of per-field `textContainsPrefix` queries plus one batch `valueMap(True)`, with `both().limit(10)` owner hop. Subgraph/deep-context share one Gremlin round-trip per depth layer. Neo4j/AGE stay CONTAINS and always `truncated: false`.

**Tech Stack:** FastAPI graph-service, gremlinpython `DriverRemoteConnection` + `Client`, JanusGraph management Groovy, pytest inspect tests (no live Janus in CI).

## Global Constraints

- Decision-api / rules remain sole allow/deny. Stored `risk_score` is a feature, not a decision.
- Do not invent graph, nodes, paths, `entity_id`, `via`, tenant, or scores. Blank `external_id` is skipped.
- `0` is a computed clean score. Unscored is `scored: false`, `risk_score: null`.
- Empty `q` → `{ "entities": [] }` 200, no store call. Do not add `truncated` on that empty-q response (omit is allowed).
- Janus match is case-insensitive **prefix** on `SEARCH_PROP_KEYS` with Python `str.casefold().startswith`. Neo4j/AGE stay case-insensitive **CONTAINS**.
- Lucene hits that fail the Python prefix re-check are dropped.
- Mixed index name `vertexSearch`, backend `search`. `tenant_id` STRING; each `SEARCH_PROP_KEYS` entry TEXTSTRING. Idempotent. REGISTERED/INSTALLED/FAILED/missing → do not block HTTP; capped scan + `truncated: true` if the cap was hit.
- Do not wait on `SchemaAction.REINDEX.get()`. Log status and serve fallback until ENABLED.
- Indexed search: per-field `has('tenant_id', t).has(field, textContainsPrefix(q)).limit(50)`, union ids, **one** batch `valueMap(True)`. No tenant-wide `elementMap` loop.
- Owner hop: `g.V(v).both().limit(10)` then batch hydrate. `cap_identifier_owners` dedupes `(via_id, owner_entity_id)` before counting.
- Subgraph / deep-context: one Gremlin round-trip per depth layer. No `g.V(v).bothE()` Python loop. No silent per-vertex edge cap. Frontend prune 3000 unchanged.
- `JANUSGRAPH_ANALYTICS_VERTEX_CAP` default 8000 (already 100–500000 in settings) is the search fallback cap.
- Rungs 1–2 parked: ingest vertices without `tenant_id` / `external_id` still miss search and cannot seed subgraph. Do not stamp ingest or create `byTenantExternal`.
- No Elasticsearch, no prefix on Neo4j/AGE, no search UI banner, no `search_keys[]`, do not edit `algorithms_janus.py`.
- Do not `git add` leftover untracked docs from other work (`docs/INDEX.md`, Help.tsx, etc.).
- CI: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py tests/test_janus_search_scale.py -v`
- Start on branch `feat/janus-search-scale` from current `master`.

## File map

| File | Responsibility |
|------|----------------|
| `services/graph-service/src/graph_service/entity_risk_score.py` | `matched_on_from_props_prefix`, `eligible_search_node_prefix`; `cap_identifier_owners` pair-dedupe |
| `services/graph-service/src/graph_service/main.py` | Wrap search hits with `truncated` when `q` is non-empty |
| `services/graph-service/src/graph_service/graph_runtime.py` | `search_entities` → `tuple[list[dict], bool]` |
| `services/graph-service/src/graph_service/neo4j_client.py` | `search_entities` returns `(rows, False)` |
| `services/graph-service/src/graph_service/age_client.py` | `search_entities` returns `(rows, False)` |
| `services/graph-service/src/graph_service/janusgraph_gremlin.py` | `Client.submit` Groovy ensure `vertexSearch`; `vertex_search_index_enabled()` |
| `services/graph-service/src/graph_service/janusgraph_store.py` | Indexed prefix search, capped fallback, layered subgraph/deep-context |
| `services/graph-service/src/graph_service/config.py` | Cap description mentions search fallback |
| `contracts/openapi/graph-service.yaml` | `truncated` on `EntitySearchResponse` |
| `frontend/src/api/mockData.ts` | `truncated: false` on non-empty search mocks |
| `frontend/src/api/client.ts` | Optional `truncated?: boolean` on the search response type |
| `services/graph-service/tests/test_entity_search.py` | HTTP truncated + keep empty-q exact body |
| `services/graph-service/tests/test_janus_search_scale.py` | Inspect + unit tests for rungs 3–5 |
| `services/graph-service/docs/janusgraph-adapter.md` | Mixed index, prefix, `truncated`, ingest-without-identity miss |
| `docs/docs/services/graph-service.md` | Janus prefix vs Neo4j/AGE CONTAINS + `truncated` |
| `docs/docs/api-reference.md` | Same |
| `docs/docs/guides/graph-analysis.md` | Same (one paragraph) |

---

### Task 1: Prefix re-check + owner pair-dedupe

**Files:**
- Modify: `services/graph-service/src/graph_service/entity_risk_score.py`
- Test: `services/graph-service/tests/test_entity_search.py` (append)

**Interfaces:**
- Consumes: existing `SEARCH_PROP_KEYS`, `SEARCH_OWNER_FANOUT`, `matched_on_from_props` (CONTAINS, Neo4j/AGE — do not change its behavior)
- Produces:
  - `matched_on_from_props_prefix(props: dict \| None, q: str) -> str \| None`
  - `eligible_search_node_prefix(entity_id: str, props: dict \| None, q: str) -> str \| None`
  - `cap_identifier_owners` still `list[dict] -> list[dict]`, but skips duplicate `(via_id, owner entity_id)` before incrementing the per-via count

- [ ] **Step 1: Create the feature branch**

```bash
git checkout master
git checkout -b feat/janus-search-scale
```

Do not stage unrelated untracked docs.

- [ ] **Step 2: Write the failing tests**

Append to `services/graph-service/tests/test_entity_search.py`. Add imports:

```python
from graph_service.entity_risk_score import (
    eligible_search_node_prefix,
    matched_on_from_props_prefix,
)
```

```python
def test_prefix_recheck_drops_non_prefix_lucene_token():
    # Lucene TEXT may match a later token prefix; Python must not.
    assert matched_on_from_props_prefix({"email": "user alice@acme.com"}, "alice") is None
    assert matched_on_from_props_prefix({"email": "alice@acme.com"}, "ALICE") == "email"
    assert matched_on_from_props_prefix({"email": "alice@acme.com"}, "lice") is None
    assert matched_on_from_props_prefix({"device_id": 99}, "99") is None
    assert matched_on_from_props_prefix({"email": "alice@acme.com"}, "") is None
    # CONTAINS helper is unchanged (Neo4j/AGE)
    assert matched_on_from_props({"email": "user alice@acme.com"}, "alice") == "email"
    assert eligible_search_node_prefix("", {"email": "alice@acme.com"}, "alice") is None
    assert eligible_search_node_prefix("e1", {"email": "alice@acme.com"}, "alice") == "email"


def test_cap_identifier_owners_dedupes_via_owner_pair():
    ident = "dev-1"
    owners = []
    for i in range(10):
        hit = search_hit_from_node(
            "t",
            f"u-{i:02d}",
            ["User"],
            {},
            matched_on="device_id",
            via={"entity_id": ident, "labels": ["Device"]},
        )
        owners.append(hit)
        owners.append(dict(hit))  # duplicate edge to the same owner
    owners.extend(
        [
            search_hit_from_node(
                "t",
                f"extra-{i}",
                ["User"],
                {},
                matched_on="device_id",
                via={"entity_id": ident, "labels": ["Device"]},
            )
            for i in range(2)
        ]
    )
    capped = cap_identifier_owners(owners)
    assert len(capped) == 10
    assert [h["entity_id"] for h in capped] == [f"u-{i:02d}" for i in range(10)]
```

Keep `test_cap_identifier_owners_fanout_10` — it must still pass (12 distinct owners → 10).

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py::test_prefix_recheck_drops_non_prefix_lucene_token tests/test_entity_search.py::test_cap_identifier_owners_dedupes_via_owner_pair -v
```

Expected: FAIL (`matched_on_from_props_prefix` not defined; pair test gets 12 not 10 because duplicates consume fan-out).

- [ ] **Step 4: Minimal implementation**

In `entity_risk_score.py`, next to `matched_on_from_props` / `eligible_search_node`:

```python
def matched_on_from_props_prefix(props: dict[str, Any] | None, q: str) -> str | None:
    needle = str(q or "").casefold()
    if not needle:
        return None
    bag = props or {}
    for key in SEARCH_PROP_KEYS:
        val = bag.get(key)
        if isinstance(val, str) and val.casefold().startswith(needle):
            return key
    return None


def eligible_search_node_prefix(entity_id: str, props: dict[str, Any] | None, q: str) -> str | None:
    eid = str(entity_id or "").strip()
    if not eid:
        return None
    bag = dict(props or {})
    bag.setdefault("external_id", eid)
    return matched_on_from_props_prefix(bag, q)
```

Replace `cap_identifier_owners` with:

```python
def cap_identifier_owners(
    hits: list[dict[str, Any]], fanout: int = SEARCH_OWNER_FANOUT
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for hit in hits:
        via = hit.get("via") or {}
        via_id = str(via.get("entity_id") or "")
        oid = str(hit.get("entity_id") or "")
        pair = (via_id, oid)
        if pair in seen:
            continue
        seen.add(pair)
        n = counts.get(via_id, 0)
        if n >= fanout:
            continue
        counts[via_id] = n + 1
        out.append(hit)
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py -v
```

Expected: PASS (including existing fan-out-10 and merge tests).

- [ ] **Step 6: Commit**

```bash
git add services/graph-service/src/graph_service/entity_risk_score.py services/graph-service/tests/test_entity_search.py
git commit -m "$(cat <<'EOF'
fix: prefix re-check and dedupe search owner fan-out

Janus Lucene must not invent prefix hits, and duplicate edges must not consume the 10-owner cap.
EOF
)"
```

---

### Task 2: HTTP `truncated` envelope

**Files:**
- Modify: `services/graph-service/src/graph_service/main.py`
- Modify: `services/graph-service/src/graph_service/graph_runtime.py`
- Modify: `services/graph-service/src/graph_service/neo4j_client.py` (return tuple only; Cypher stays CONTAINS)
- Modify: `services/graph-service/src/graph_service/age_client.py` (same)
- Modify: `contracts/openapi/graph-service.yaml`
- Modify: `frontend/src/api/mockData.ts`
- Modify: `frontend/src/api/client.ts` (type only)
- Modify: `services/graph-service/tests/test_entity_search.py`
- Modify: `services/graph-service/src/graph_service/janusgraph_store.py` — temporary `(rows, False)` return so the tuple contract type-checks until Task 3. Do **not** rewrite the scan yet.

**Interfaces:**
- Consumes: store `search_entities(...)` 
- Produces: `async search_entities(...) -> tuple[list[dict[str, Any]], bool]` from graph_runtime and all three stores. HTTP with non-empty `q`: `{ "entities": rows, "truncated": bool }`. Empty `q` still `{ "entities": [] }` and must not call the store.

- [ ] **Step 1: Write the failing HTTP tests**

Change the search HTTP label/limit test mock to return a tuple and assert `truncated`:

```python
def test_search_http_empty_q_no_store(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(return_value=([], False))
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        data = client.get("/v1/entities/search", params={"tenant_id": "t"}).json()
    assert data == {"entities": []}
    store.assert_not_called()


def test_search_http_forwards_label_and_limit(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(return_value=(
        [
            {
                "entity_id": "fraud_frank",
                "tenant_id": "t",
                "labels": ["Person"],
                "scored": True,
                "risk_score": 72,
            }
        ],
        False,
    ))
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        data = client.get(
            "/v1/entities/search",
            params={"tenant_id": "t", "q": "frank", "label": "Person", "limit": 999},
        ).json()
    assert data["entities"][0]["entity_id"] == "fraud_frank"
    assert data["truncated"] is False
    store.assert_awaited_once()
    kwargs = store.await_args.kwargs
    assert kwargs["q"] == "frank"
    assert kwargs["label"] == "Person"
    assert kwargs["limit"] == 50


def test_search_http_truncated_true(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(return_value=([], True))
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        data = client.get(
            "/v1/entities/search",
            params={"tenant_id": "t", "q": "x"},
        ).json()
    assert data == {"entities": [], "truncated": True}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py::test_search_http_forwards_label_and_limit tests/test_entity_search.py::test_search_http_truncated_true -v
```

Expected: FAIL (`truncated` missing / mock return is a list so unpack errors after you change the handler — write tests first against current handler, which returns `{entities}` only).

- [ ] **Step 3: Implementation**

`graph_runtime.py`:

```python
async def search_entities(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> tuple[list[dict[str, Any]], bool]:
    return await _store().search_entities(tenant_id, q, label=label, limit=limit)
```

`neo4j_client.py` — keep the Cypher body; change only the last line:

```python
    return merge_search_hits(directs + owners, label=label, limit=limit), False
```

`age_client.py` — same last line.

`janusgraph_store.py` `search_entities` — change the inner return and async return to a tuple **without** rewriting the scan:

```python
        return merge_search_hits(directs + owners, label=label, limit=limit), False

    return await run_in_gremlin_thread(_search_entities_sync)
```

Update the annotated return type on all three `search_entities` functions to `tuple[list[dict[str, Any]], bool]`.

`main.py`:

```python
@app.get("/v1/entities/search")
async def entities_search(
    tenant_id: str, q: str = "", label: str | None = None, limit: int = 20
):
    needle = (q or "").strip()[:256]
    if not needle:
        return {"entities": []}
    lab = (label or "").strip() or None
    rows, truncated = await search_entities(
        tenant_id, q=needle, label=lab, limit=clamp_search_limit(limit)
    )
    return {"entities": rows, "truncated": bool(truncated)}
```

OpenAPI `EntitySearchResponse`:

```yaml
    EntitySearchResponse:
      type: object
      required: [entities, truncated]
      properties:
        entities:
          type: array
          items: { $ref: "#/components/schemas/EntitySearchHit" }
        truncated:
          type: boolean
          default: false
          description: >
            True when JanusGraph served search from a capped tenant scan because
            mixed index vertexSearch was not ENABLED. Neo4j/AGE always false.
            Omitted on empty q (no scan).
```

Update `/v1/entities/search` 200 description to mention `truncated` and Janus prefix vs Neo4j/AGE CONTAINS.

`frontend/src/api/client.ts` — search return type:

```typescript
return request<{ entities: GraphSearchHit[]; truncated?: boolean }>(`/api/graph/v1/entities/search?${q}`);
```

`frontend/src/api/mockData.ts` — every non-empty search return adds `truncated: false`. Empty `q` stays `{ entities: [] }`. Example:

```typescript
if (!q.trim()) return { entities: [] };
// ...
return { entities, truncated: false };
// frank fixture:
return { entities: [ ... ], truncated: false };
```

- [ ] **Step 4: Run tests**

```bash
cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py -v
```

Expected: PASS. Confirm Neo4j/AGE sources still contain `CONTAINS` and do not contain `textContainsPrefix`:

```python
# already in test_neo4j_search_cypher_is_parameterized_contains / test_age_search_cypher_contains_and_tenant
```

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/main.py \
  services/graph-service/src/graph_service/graph_runtime.py \
  services/graph-service/src/graph_service/neo4j_client.py \
  services/graph-service/src/graph_service/age_client.py \
  services/graph-service/src/graph_service/janusgraph_store.py \
  services/graph-service/tests/test_entity_search.py \
  contracts/openapi/graph-service.yaml \
  frontend/src/api/client.ts \
  frontend/src/api/mockData.ts
git commit -m "$(cat <<'EOF'
feat: return truncated on graph entity search

Callers can tell a Janus capped scan from a complete index hit; Neo4j/AGE stay false.
EOF
)"
```

---

### Task 3: Mixed index + Janus prefix search

**Files:**
- Modify: `services/graph-service/src/graph_service/janusgraph_gremlin.py`
- Modify: `services/graph-service/src/graph_service/janusgraph_store.py`
- Modify: `services/graph-service/src/graph_service/config.py` (description only)
- Create: `services/graph-service/tests/test_janus_search_scale.py`

**Interfaces:**
- Consumes: `SEARCH_PROP_KEYS`, `eligible_search_node_prefix`, `cap_identifier_owners`, `settings.janusgraph_analytics_vertex_cap`, `get_traversal_source`
- Produces:
  - `ensure_vertex_search_index() -> None` (idempotent; sets module flag)
  - `vertex_search_index_enabled() -> bool`
  - `janusgraph_store.search_entities(...) -> tuple[list[dict], bool]`
  - Groovy mixed index `vertexSearch` on backend `search`

- [ ] **Step 1: Write the failing inspect tests**

Create `services/graph-service/tests/test_janus_search_scale.py`:

```python
import inspect

from graph_service import age_client, janusgraph_gremlin, janusgraph_store, neo4j_client
from graph_service.entity_risk_score import SEARCH_PROP_KEYS


def test_janus_search_uses_prefix_index_and_batch_hydrate():
    src = inspect.getsource(janusgraph_store.search_entities)
    gremlin_src = inspect.getsource(janusgraph_gremlin)
    assert "textContainsPrefix" in src
    assert "valueMap" in src
    assert "both().limit(10)" in src
    assert "vertexSearch" in gremlin_src
    assert "Client" in gremlin_src
    assert "submit" in gremlin_src
    assert "truncated" in src
    assert "janusgraph_analytics_vertex_cap" in src
    assert "eligible_search_node_prefix" in src
    assert "elementMap" not in src
    assert "for v in g.V().has(\"tenant_id\")" not in src
    assert "for v in g.V().has('tenant_id')" not in src


def test_janus_fallback_mentions_cap_and_truncated():
    src = inspect.getsource(janusgraph_store.search_entities)
    assert "limit(" in src
    assert "truncated" in src


def test_cypher_backends_keep_contains():
    from graph_service.entity_risk_score import cypher_search_prop_predicate

    nsrc = inspect.getsource(neo4j_client.search_entities)
    asrc = inspect.getsource(age_client.search_entities)
    assert "CONTAINS" in inspect.getsource(cypher_search_prop_predicate)
    assert "textContainsPrefix" not in nsrc
    assert "textContainsPrefix" not in asrc


def test_vertex_search_groovy_covers_allowlist():
    src = inspect.getsource(janusgraph_gremlin)
    assert "vertexSearch" in src
    assert "Mapping.STRING" in src or "STRING" in src
    assert "TEXTSTRING" in src
    assert "index.search" in src or '"search"' in src or "'search'" in src
    for key in SEARCH_PROP_KEYS:
        assert key in src or "SEARCH_PROP_KEYS" in src
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_janus_search_scale.py -v
```

Expected: FAIL (`textContainsPrefix` / `vertexSearch` / `Client` missing; tenant `elementMap` loop still present).

- [ ] **Step 3: Gremlin Client + Groovy ensure**

In `janusgraph_gremlin.py` add (keep existing connection helpers). Import `SEARCH_PROP_KEYS` inside the groovy builder to avoid import cycles if needed — `entity_risk_score` does not import gremlin, so a top-level import is fine.

```python
from gremlin_python.driver.client import Client

from .entity_risk_score import SEARCH_PROP_KEYS

_vertex_search_enabled = False
_vertex_search_checked = False


def _vertex_search_groovy() -> str:
    # Frozen allowlist identifiers only — never interpolate user q.
    key_decls: list[str] = []
    add_keys: list[str] = []
    status_keys = ["tenant_id", *SEARCH_PROP_KEYS]
    for i, key in enumerate(SEARCH_PROP_KEYS):
        key_decls.append(
            f"k{i} = mgmt.getPropertyKey('{key}')\n"
            f"if (k{i} == null) {{ k{i} = mgmt.makePropertyKey('{key}').dataType(String.class).make() }}"
        )
        add_keys.append(f"b.addKey(k{i}, Mapping.TEXTSTRING.asParameter())")
    status_loop = "\n".join(
        f"pk = mgmt.getPropertyKey('{k}'); "
        f"if (pk == null || idx.getIndexStatus(pk) != SchemaStatus.ENABLED) {{ allEnabled = false }}"
        for k in status_keys
    )
    decls = "\n".join(key_decls)
    adds = "\n".join(add_keys)
    return f"""
import org.apache.tinkerpop.gremlin.structure.Vertex
import org.janusgraph.core.schema.Mapping
import org.janusgraph.core.schema.SchemaStatus
mgmt = graph.openManagement()
try {{
  idx = mgmt.getGraphIndex('vertexSearch')
  if (idx == null) {{
    tid = mgmt.getPropertyKey('tenant_id')
    if (tid == null) {{ tid = mgmt.makePropertyKey('tenant_id').dataType(String.class).make() }}
    {decls}
    b = mgmt.buildIndex('vertexSearch', Vertex.class)
    b.addKey(tid, Mapping.STRING.asParameter())
    {adds}
    b.buildMixedIndex('search')
    mgmt.commit()
    mgmt = graph.openManagement()
    idx = mgmt.getGraphIndex('vertexSearch')
  }}
  if (idx == null) {{ mgmt.rollback(); return 'MISSING' }}
  allEnabled = true
  {status_loop}
  mgmt.rollback()
  return allEnabled ? 'ENABLED' : 'REGISTERED'
}} catch (Exception e) {{
  try {{ mgmt.rollback() }} catch (Exception ignored) {{}}
  return 'FAILED'
}}
"""


def vertex_search_index_enabled() -> bool:
    return _vertex_search_enabled


def ensure_vertex_search_index() -> None:
    """Idempotent mixed-index ensure. Never wait for REINDEX. Never raise to HTTP."""
    global _vertex_search_enabled, _vertex_search_checked
    if _vertex_search_checked:
        return
    _vertex_search_checked = True
    client = None
    try:
        url = settings.janusgraph_gremlin_url.strip()
        src = settings.janusgraph_traversal_source.strip() or "g"
        client = Client(url, src)
        raw = client.submit(_vertex_search_groovy()).all().result()
        status = str(raw[0] if raw else "FAILED").upper()
        _vertex_search_enabled = status == "ENABLED"
        if not _vertex_search_enabled:
            log.warning(
                "Janus mixed index vertexSearch status=%s; search uses capped tenant scan",
                status,
            )
    except Exception:
        log.exception("Janus mixed index vertexSearch ensure failed; search uses capped tenant scan")
        _vertex_search_enabled = False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as e:
                log.warning("Gremlin management client close: %s", e)


def get_traversal_source():
    global _conn
    if _conn is None:
        url = settings.janusgraph_gremlin_url.strip()
        src = settings.janusgraph_traversal_source.strip() or "g"
        log.info("JanusGraph Gremlin: connecting to %s traversal=%s", url, src)
        _conn = DriverRemoteConnection(url, src)
        ensure_vertex_search_index()
    return traversal().withRemote(_conn)


def close_janus_connection() -> None:
    global _conn, _vertex_search_checked, _vertex_search_enabled
    if _conn is not None:
        try:
            _conn.close()
        except Exception as e:
            log.warning("Gremlin connection close: %s", e)
        _conn = None
    _vertex_search_checked = False
    _vertex_search_enabled = False
```

Python `except` on `Client.submit` covers a missing `graph` binding (log + fallback scan). Do not wait on REINDEX.

- [ ] **Step 4: Rewrite Janus `search_entities`**

In `janusgraph_store.py`:

Imports to add:

```python
from gremlin_python.process.traversal import P, T

from .config import settings
from .janusgraph_gremlin import (
    get_traversal_source,
    run_in_gremlin_thread,
    vertex_search_index_enabled,
)
```

Helpers (near `_vertex_to_node`):

```python
def _valuemap_to_element(vm: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (vm or {}).items():
        if k in (T.id, "id") or str(k) in ("id", "T.id"):
            out["id"] = v
            continue
        if k in (T.label, "label") or str(k) in ("label", "T.label"):
            out["label"] = v[0] if isinstance(v, list) and v else v
            continue
        key = str(k)
        if isinstance(v, (list, tuple)):
            out[key] = v[0] if len(v) == 1 else list(v)
        else:
            out[key] = v
    return out


def _labels_from_em(em: dict[str, Any]) -> list[str]:
    raw_lbl = em.get("label")
    if isinstance(raw_lbl, list):
        return [str(x) for x in raw_lbl] if raw_lbl else ["Custom"]
    return [str(raw_lbl or "Custom")]


def _batch_valuemap(g, vertices: list[Any]) -> list[dict[str, Any]]:
    if not vertices:
        return []
    raw = g.V(*vertices).valueMap(True).toList()
    return [_valuemap_to_element(m) for m in raw]
```

Replace `search_entities` (keep `clamp_search_limit` / merge / owner labels):

```python
async def search_entities(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> tuple[list[dict[str, Any]], bool]:
    from .entity_risk_score import (
        SEARCH_PROP_KEYS,
        cap_identifier_owners,
        clamp_search_limit,
        eligible_search_node_prefix,
        labels_are_identifier,
        labels_are_owner,
        merge_search_hits,
        search_hit_from_node,
    )

    limit = clamp_search_limit(limit)
    needle = str(q or "")

    def _capped_scan(g) -> tuple[list[Any], bool]:
        cap = int(settings.janusgraph_analytics_vertex_cap)
        found = g.V().has("tenant_id", tenant_id).limit(cap).toList()
        return found, len(found) >= cap

    def _search_entities_sync() -> tuple[list[dict[str, Any]], bool]:
        g = get_traversal_source()
        truncated = False
        vertices: list[Any] = []
        if vertex_search_index_enabled():
            try:
                seen: set[Any] = set()
                for field in SEARCH_PROP_KEYS:
                    found = (
                        g.V()
                        .has("tenant_id", tenant_id)
                        .has(field, P("textContainsPrefix", needle))
                        .limit(50)
                        .toList()
                    )
                    for v in found:
                        vid = getattr(v, "id", v)
                        if vid in seen:
                            continue
                        seen.add(vid)
                        vertices.append(v)
            except Exception:
                log.exception("Janus textContainsPrefix failed; using capped tenant scan")
                vertices, truncated = _capped_scan(g)
        else:
            vertices, truncated = _capped_scan(g)

        maps = _batch_valuemap(g, vertices)
        directs: list[dict[str, Any]] = []
        ident_vs: list[tuple[str, dict[str, Any], Any]] = []
        for v, em in zip(vertices, maps):
            if str(em.get("label") or "") == "GraphRiskStats":
                continue
            eid = str(em.get("external_id") or "").strip()
            labels = _labels_from_em(em)
            props = {k: val for k, val in em.items() if k not in ("id", "label")}
            matched = eligible_search_node_prefix(eid, props, needle)
            if not matched:
                continue
            hit = search_hit_from_node(
                tenant_id, eid, labels, props, matched_on=matched, via=None
            )
            directs.append(hit)
            if labels_are_identifier(labels):
                ident_vs.append((eid, hit, v))

        owner_meta: list[tuple[Any, dict[str, Any]]] = []
        for _eid, ident, v in ident_vs:
            for nv in g.V(v).both().limit(10).toList():
                owner_meta.append((nv, ident))
        unique_owners: list[Any] = []
        seen_n: set[Any] = set()
        for nv, _ident in owner_meta:
            nid = getattr(nv, "id", None)
            if nid in seen_n:
                continue
            seen_n.add(nid)
            unique_owners.append(nv)
        hydrated = {
            getattr(nv, "id", None): em
            for nv, em in zip(unique_owners, _batch_valuemap(g, unique_owners))
        }
        raw_owners: list[dict[str, Any]] = []
        for nv, ident in owner_meta:
            em = hydrated.get(getattr(nv, "id", None))
            if not em:
                continue
            oid = str(em.get("external_id") or "").strip()
            olabels = _labels_from_em(em)
            if not oid or not labels_are_owner(olabels):
                continue
            oprops = {k: val for k, val in em.items() if k not in ("id", "label")}
            raw_owners.append(
                search_hit_from_node(
                    tenant_id,
                    oid,
                    olabels,
                    oprops,
                    matched_on=ident["matched_on"],
                    via={"entity_id": ident["entity_id"], "labels": ident["labels"]},
                )
            )
        raw_owners.sort(key=lambda h: str(h.get("entity_id") or ""))
        owners = cap_identifier_owners(raw_owners)
        rows = merge_search_hits(directs + owners, label=label, limit=limit)
        return rows, truncated

    return await run_in_gremlin_thread(_search_entities_sync)
```

Indexed path `truncated` is `False` unless the fallback branch ran. Do not return 5xx or invent hits.

`config.py` Field description for `janusgraph_analytics_vertex_cap`:

```python
description="Max vertices loaded into memory for JanusGraph analytics and search fallback when vertexSearch is not ENABLED.",
```

- [ ] **Step 5: Run tests**

```bash
cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_janus_search_scale.py tests/test_entity_search.py -v
```

Expected: PASS. `test_janus_search_filters_in_python_not_full_graph_scan_without_tenant` in `test_entity_search.py` still asserts `"both()"` and `"eligible_search_node"` — **update that test** in this task:

```python
def test_janus_search_filters_in_python_not_full_graph_scan_without_tenant():
    src = inspect.getsource(janusgraph_store.search_entities)
    assert "tenant_id" in src
    assert "GraphRiskStats" in src
    assert "eligible_search_node_prefix" in src
    assert "merge_search_hits" in src
    assert "both().limit(10)" in src
    assert "search_hit_from_node" in src
```

- [ ] **Step 6: Commit**

```bash
git add services/graph-service/src/graph_service/janusgraph_gremlin.py \
  services/graph-service/src/graph_service/janusgraph_store.py \
  services/graph-service/src/graph_service/config.py \
  services/graph-service/tests/test_janus_search_scale.py \
  services/graph-service/tests/test_entity_search.py
git commit -m "$(cat <<'EOF'
feat: Janus typeahead via mixed-index prefix search

Stop scanning every tenant vertex per keystroke; fall back to a capped scan when vertexSearch is not ENABLED.
EOF
)"
```

---

### Task 4: Layered subgraph and deep-context

**Files:**
- Modify: `services/graph-service/src/graph_service/janusgraph_store.py`
- Modify: `services/graph-service/tests/test_janus_search_scale.py`

**Interfaces:**
- Consumes: `_valuemap_to_element`, `_vertex_to_node`, `shape_deep_context_from_nodes`
- Produces: `_walk_incident_layers(g, root, depth) -> tuple[list[dict], list[dict]]` (element-like maps, edges). `_query_subgraph_sync` and `_query_entity_deep_context_sync` call it. No `g.V(v).bothE()` in those functions.

- [ ] **Step 1: Write the failing inspect test**

Append to `tests/test_janus_search_scale.py`:

```python
def test_janus_subgraph_one_roundtrip_per_layer():
    sub = inspect.getsource(janusgraph_store._query_subgraph_sync)
    deep = inspect.getsource(janusgraph_store._query_entity_deep_context_sync)
    walk = inspect.getsource(janusgraph_store._walk_incident_layers)
    assert "g.V(v).bothE()" not in sub
    assert "g.V(v).bothE()" not in deep
    assert "bothE().toList()" not in sub
    assert "elementMap" not in sub
    assert "elementMap" not in deep
    assert "valueMap" in walk
    assert "bothE" in walk
    assert "for layer" in walk or "range(" in walk
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_janus_search_scale.py::test_janus_subgraph_one_roundtrip_per_layer -v
```

Expected: FAIL (`_walk_incident_layers` missing; `g.V(v).bothE()` still in subgraph).

- [ ] **Step 3: Implementation**

Replace `_query_subgraph_sync` / `_query_entity_deep_context_sync` loops with:

```python
def _walk_incident_layers(g, root: Any, depth: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One Gremlin round-trip per depth layer. Super-node RAM is a known ceiling (no per-vertex edge cap)."""
    depth = max(1, min(int(depth), 5))
    nodes_out: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    seen_nodes: set[str] = set()

    def add_em(em: dict[str, Any]) -> None:
        eid = str(em.get("external_id", "") or "")
        if not eid or eid in seen_nodes:
            return
        seen_nodes.add(eid)
        nodes_out.append(_vertex_to_node(em))

    root_maps = _batch_valuemap(g, [root])
    if not root_maps:
        return [], []
    add_em(root_maps[0])

    frontier: list[Any] = [root]
    visited: set[Any] = {getattr(root, "id", root)}
    for _layer in range(depth):
        if not frontier:
            break
        rows = (
            g.V(*frontier)
            .bothE()
            .as_("e")
            .otherV()
            .as_("o")
            .project("eid", "elabel", "from_ext", "to_ext", "oid", "omap")
            .by(__.select("e").id())
            .by(__.select("e").label())
            .by(__.select("e").outV().values("external_id"))
            .by(__.select("e").inV().values("external_id"))
            .by(__.select("o").id())
            .by(__.select("o").valueMap(True))
            .toList()
        )
        next_frontier: list[Any] = []
        next_seen: set[Any] = set()
        for row in rows or []:
            ekey = str(row.get("eid"))
            if ekey in seen_edges:
                continue
            seen_edges.add(ekey)
            edges_out.append(
                {
                    "from_id": str(row.get("from_ext") or ""),
                    "to_id": str(row.get("to_ext") or ""),
                    "type": str(row.get("elabel") or ""),
                    "properties": {},
                }
            )
            oid = row.get("oid")
            if oid not in visited and oid not in next_seen:
                visited.add(oid)
                next_seen.add(oid)
                next_frontier.append(oid)
            omap = row.get("omap")
            if isinstance(omap, dict):
                add_em(_valuemap_to_element(omap))
        frontier = next_frontier
    return nodes_out, edges_out


def _query_subgraph_sync(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    g = get_traversal_source()
    depth = max(1, min(int(depth), 5))
    root_list = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(1).toList()
    if not root_list:
        return {"nodes": [], "edges": []}
    nodes_out, edges_out = _walk_incident_layers(g, root_list[0], depth)
    return {"nodes": nodes_out, "edges": edges_out}


def _query_entity_deep_context_sync(tenant_id: str, entity_id: str) -> dict[str, Any] | None:
    g = get_traversal_source()
    root_list = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(1).toList()
    if not root_list:
        return None
    nodes_out, _edges = _walk_incident_layers(g, root_list[0], 2)
    return shape_deep_context_from_nodes(entity_id, tenant_id, nodes_out)
```

Do not change the HTTP subgraph prune or the 3000-node frontend cap. Do not add a per-vertex edge limit. Do not touch `algorithms_janus.py`.

If `g.V(*frontier)` with mixed vertex objects vs raw ids is picky, keep frontier as the objects returned by `otherV` instead of ids: change `next_frontier.append(oid)` to stash the other vertex from the projection (add `.by(__.select("o"))` as `"overtex"` and append that). Ids are fine if `g.V(id)` works on this server (it does for JanusGraph long ids).

- [ ] **Step 4: Run tests**

```bash
cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_janus_search_scale.py tests/test_entity_search.py tests/test_subgraph_risk_fields.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/janusgraph_store.py \
  services/graph-service/tests/test_janus_search_scale.py
git commit -m "$(cat <<'EOF'
perf: Janus subgraph walks one Gremlin trip per hop

Neighborhood load was one bothE/elementMap per vertex; a super-node still fits in RAM (known ceiling).
EOF
)"
```

---

### Task 5: Docs honesty

**Files:**
- Modify: `services/graph-service/docs/janusgraph-adapter.md`
- Modify: `docs/docs/services/graph-service.md` (Search Entities section)
- Modify: `docs/docs/api-reference.md` (`GET /v1/entities/search`)
- Modify: `docs/docs/guides/graph-analysis.md` (Search paragraph)

**Interfaces:** none. No code.

- [ ] **Step 1: Adapter**

Replace the Indexes bullets in `janusgraph-adapter.md` with:

- On first graph-service connect, management Groovy creates mixed index `vertexSearch` on backend `search` (demo Lucene: `index.search.backend = lucene`) if missing: `tenant_id` STRING, allowlisted search keys TEXTSTRING (`external_id`, `email`, `device_id`, `address`, `line1`, `phone`, `ip`, `user_id`, `card_id`).
- Search uses `textContainsPrefix` (case-insensitive prefix) plus a Python `startswith` re-check. Neo4j/AGE remain CONTAINS.
- If `vertexSearch` is not ENABLED (REGISTERED/INSTALLED/FAILED/mgmt error), search scans at most `JANUSGRAPH_ANALYTICS_VERTEX_CAP` (default 8000) vertices and sets `truncated: true` when that cap is hit. HTTP is not blocked for reindex.
- Composite unique `(tenant_id, external_id)` (`byTenantExternal`) is **not** created in this change (parked). GRAPH_INGEST vertices that never received `tenant_id` / `external_id` still miss typeahead and cannot seed subgraph.
- Subgraph / deep-context: one Gremlin round-trip per depth layer. Super-node neighborhoods can be large in RAM (no silent per-vertex edge cap).

Fix the adapter table if it still says `GRAPH_BACKEND` default `neo4j` — `config.py` default is `janusgraph`. Do not rewrite the whole adapter.

- [ ] **Step 2: Product docs**

Search Entities / api-reference / graph-analysis Search paragraph, same facts:

- Neo4j and AGE: case-insensitive CONTAINS on the allowlist.
- JanusGraph: case-insensitive **prefix** on the same allowlist.
- Response includes `truncated` (boolean, default false). Empty `q` is still `{ "entities": [] }` with no scan (`truncated` omitted).
- Ingest without `tenant_id`/`external_id` does not appear in search.

Sample JSON with `q` present adds `"truncated": false`.

- [ ] **Step 3: Commit**

```bash
git add services/graph-service/docs/janusgraph-adapter.md \
  docs/docs/services/graph-service.md \
  docs/docs/api-reference.md \
  docs/docs/guides/graph-analysis.md
git commit -m "$(cat <<'EOF'
docs: Janus prefix search, truncated, and ingest identity gap

Operators should not expect CONTAINS or complete typeahead on ingest vertices missing tenant_id/external_id.
EOF
)"
```

---

## Self-review (spec coverage)

| Spec requirement | Task |
|---|---|
| Janus prefix + Python startswith re-check | 1, 3 |
| Lucene extra token dropped | 1 |
| Mixed index `vertexSearch` / `search` / STRING+TEXTSTRING via Client.submit | 3 |
| Idempotent; REGISTERED does not block HTTP | 3 |
| Per-field `textContainsPrefix` union + batch valueMap | 3 |
| Owner `both().limit(10)` + pair-dedupe cap | 1, 3 |
| Fallback `limit(analytics cap)` + `truncated` | 2, 3 |
| HTTP `{entities, truncated}`; empty q unchanged no store | 2 |
| OpenAPI + mocks `truncated` | 2 |
| Neo4j/AGE CONTAINS, truncated false | 2, 3 inspect |
| Layered subgraph/deep-context; no per-vertex bothE | 4 |
| Docs: prefix vs CONTAINS, truncated, ingest miss | 5 |
| Out of scope: rungs 1–2, ES, UI banner, algorithms_janus, subgraph edge cap | (not in plan) |
