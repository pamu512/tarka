# Graph Investigation Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge Graph Explorer and Link Analysis into one Palantir-style `/graph` workspace: graph entity search, type histogram / risk / growth filters, 1-hop expand merge, path overlay, dossier column.

**Architecture:** New `GET /v1/entities/search` on graph-service (Neo4j + Janus + AGE). Frontend domain helpers own URL parse, client-side filters, and expand-union. `GraphInvestigationPage` at `/graph` uses the existing force-graph and `GraphContextPanel`. Canvas paints stored subgraph `risk_score` only (no live entity-risk / risk-propagation on seed load).

**Tech Stack:** FastAPI graph-service, Cypher/Gremlin, React + vis-free force-graph, vitest, pytest TestClient mocks.

## Global Constraints

- Decision-api / rules remain sole allow/deny. Stored `risk_score` is a feature, not a decision.
- Do not invent graph, nodes, paths, or scores when the graph plane is down.
- `0` is a computed clean score. Unscored is `scored: false`, `risk_score: null` — never treat null as 0 in filters or paint.
- Search matches `external_id` only (parameterized contains). No property-bag / Elasticsearch.
- Empty `q` → `{ "entities": [] }` 200, no scan.
- Omni-search is case-table only — do not use it as the workspace typeahead.
- No new investigation-agent or Shadow tool.
- No ontology editor. Schema chips are read-only from `GET /v1/schema/{tenant_id}`.
- `/graph/mule-path` stays. vis-network Explorer goes away.
- CI graph-service: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest …`
- CI frontend: `cd frontend && npm test -- <file>`

## File map

| File | Responsibility |
|------|----------------|
| `services/graph-service/src/graph_service/entity_risk_score.py` | `clamp_search_limit`, `search_hit_from_node` |
| `services/graph-service/src/graph_service/graph_runtime.py` | `search_entities` dispatch |
| `services/graph-service/src/graph_service/neo4j_client.py` | Cypher contains search |
| `services/graph-service/src/graph_service/janusgraph_store.py` | Tenant scan + Python contains (same as top-N) |
| `services/graph-service/src/graph_service/age_client.py` | AGE Cypher contains search |
| `services/graph-service/src/graph_service/main.py` | `GET /v1/entities/search` |
| `services/graph-service/tests/test_entity_search.py` | HTTP + Neo4j query tests |
| `contracts/openapi/graph-service.yaml` | Search path + schema |
| `frontend/src/domain/graphInvestigation.ts` | URL parse, filters, merge, stored displayRisk |
| `frontend/src/domain/graphInvestigation.test.ts` | Domain tests |
| `frontend/src/api/client.ts` | `searchEntities`, `entityRiskTop`, `schema`, pathExplain query names |
| `frontend/src/api/mockData.ts` | Search / top / schema mocks |
| `frontend/src/components/LinkAnalysisForceGraph.tsx` | Path highlight + double-click |
| `frontend/src/pages/GraphInvestigationPage.tsx` | Workspace page |
| `frontend/src/App.tsx` | Route swap + link-analysis redirect |
| `frontend/src/pages/GraphExplorer.tsx` | **Delete** after swap |
| `frontend/src/pages/LinkAnalysisPage.tsx` | **Delete** after swap |
| `frontend/src/components/CommandPalette.tsx` | Label “Graph” |
| `frontend/src/config/accessModuleCatalog.ts` | Label “Graph” |
| `docs/docs/services/graph-service.md` | Search endpoint |
| `docs/docs/api-reference.md` | Search row |

---

### Task 1: Entity search API (Neo4j + HTTP)

**Files:**
- Modify: `services/graph-service/src/graph_service/entity_risk_score.py`
- Modify: `services/graph-service/src/graph_service/graph_runtime.py`
- Modify: `services/graph-service/src/graph_service/neo4j_client.py`
- Modify: `services/graph-service/src/graph_service/main.py`
- Test: `services/graph-service/tests/test_entity_search.py`

**Interfaces:**
- Consumes: `stored_risk_view(props) -> dict`
- Produces:
  - `clamp_search_limit(limit: int | None) -> int` — default 20, clamp 1–50
  - `search_hit_from_node(tenant_id: str, entity_id: str, labels: list[str], props: dict) -> dict` with keys `entity_id`, `tenant_id`, `labels`, `scored`, `risk_score`
  - `async search_entities(tenant_id: str, q: str, label: str | None = None, limit: int = 20) -> list[dict]`
  - HTTP `GET /v1/entities/search` → `{ "entities": [...] }`

- [ ] **Step 1: Write the failing tests**

Create `services/graph-service/tests/test_entity_search.py`:

```python
import inspect
from unittest.mock import AsyncMock

from graph_service.entity_risk_score import clamp_search_limit, search_hit_from_node
from graph_service import neo4j_client


def test_clamp_search_limit():
    assert clamp_search_limit(None) == 20
    assert clamp_search_limit(0) == 1
    assert clamp_search_limit(99) == 50
    assert clamp_search_limit(7) == 7


def test_search_hit_unscored_is_null_not_zero():
    hit = search_hit_from_node("t", "a", ["Account"], {})
    assert hit["scored"] is False
    assert hit["risk_score"] is None
    assert hit["labels"] == ["Account"]


def test_search_hit_scored_zero_is_zero():
    hit = search_hit_from_node(
        "t",
        "a",
        ["Person"],
        {"risk_computed_at": "2026-08-13T00:00:00Z", "risk_score": 0, "risk_factors": []},
    )
    assert hit["scored"] is True
    assert hit["risk_score"] == 0


def test_neo4j_search_cypher_is_parameterized_contains():
    src = inspect.getsource(neo4j_client.search_entities)
    assert "CONTAINS" in src
    assert "$q" in src
    assert "$tenant_id" in src
    assert "GraphRiskStats" in src
    assert "toLower" in src


def test_search_http_empty_q_no_store(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(return_value=[{"entity_id": "should_not_run"}])
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        data = client.get("/v1/entities/search", params={"tenant_id": "t"}).json()
    assert data == {"entities": []}
    store.assert_not_called()


def test_search_http_passes_label_and_clamps(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(return_value=[
        {"entity_id": "fraud_frank", "tenant_id": "t", "labels": ["Person"], "scored": True, "risk_score": 72},
    ])
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        data = client.get(
            "/v1/entities/search",
            params={"tenant_id": "t", "q": "frank", "label": "Person", "limit": 999},
        ).json()
    assert data["entities"][0]["entity_id"] == "fraud_frank"
    store.assert_awaited_once()
    kwargs = store.await_args.kwargs
    assert kwargs["q"] == "frank"
    assert kwargs["label"] == "Person"
    assert kwargs["limit"] == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py -v`

Expected: FAIL — `search_hit_from_node` / `search_entities` not defined.

- [ ] **Step 3: Implement helpers + Neo4j + HTTP**

Append to `entity_risk_score.py`:

```python
def clamp_search_limit(limit: int | None) -> int:
    if limit is None:
        return 20
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return 20
    return max(1, min(50, n))


def search_hit_from_node(
    tenant_id: str, entity_id: str, labels: list, props: dict[str, Any] | None
) -> dict[str, Any]:
    view = stored_risk_view(props)
    labs = [str(x) for x in (labels or [])]
    return {
        "entity_id": str(entity_id),
        "tenant_id": str(tenant_id),
        "labels": labs,
        "scored": bool(view["scored"]),
        "risk_score": view["risk_score"],
    }
```

Add `async def search_entities(...)` to `neo4j_client.py` (exclude `GraphRiskStats`; parameterized `toLower(n.external_id) CONTAINS toLower($q)`; optional `$label IN labels(n)`; `ORDER BY CASE WHEN n.risk_computed_at IS NULL THEN 1 ELSE 0 END, n.risk_score DESC, n.external_id ASC`; `LIMIT $limit`). Map each row through `search_hit_from_node`.

Dispatch in `graph_runtime.py`:

```python
async def search_entities(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    return await _store().search_entities(tenant_id, q, label=label, limit=limit)
```

In `main.py`:

```python
from .entity_risk_score import clamp_search_limit
from .graph_runtime import search_entities

@app.get("/v1/entities/search")
async def entities_search(
    tenant_id: str, q: str = "", label: str | None = None, limit: int = 20
):
    needle = (q or "").strip()[:256]
    if not needle:
        return {"entities": []}
    lab = (label or "").strip() or None
    rows = await search_entities(
        tenant_id, needle, label=lab, limit=clamp_search_limit(limit)
    )
    return {"entities": rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/entity_risk_score.py \
  services/graph-service/src/graph_service/graph_runtime.py \
  services/graph-service/src/graph_service/neo4j_client.py \
  services/graph-service/src/graph_service/main.py \
  services/graph-service/tests/test_entity_search.py
git commit -m "Add graph entity search by id contains and optional type."
```

---

### Task 2: Janus and AGE search twins

**Files:**
- Modify: `services/graph-service/src/graph_service/janusgraph_store.py`
- Modify: `services/graph-service/src/graph_service/age_client.py`
- Modify: `services/graph-service/tests/test_entity_search.py`

**Interfaces:**
- Consumes: `search_hit_from_node`, `clamp_search_limit`
- Produces: `janusgraph_store.search_entities` and `age_client.search_entities` with the same signature as Neo4j

- [ ] **Step 1: Write failing inspect tests**

Append to `tests/test_entity_search.py`:

```python
from graph_service import age_client, janusgraph_store


def test_janus_search_filters_in_python_not_full_graph_scan_without_tenant():
    src = inspect.getsource(janusgraph_store.search_entities)
    assert "tenant_id" in src
    assert "external_id" in src
    assert "GraphRiskStats" in src
    assert "search_hit_from_node" in src


def test_age_search_cypher_contains_and_tenant():
    src = inspect.getsource(age_client.search_entities)
    assert "CONTAINS" in src or "contains" in src
    assert "tenant_id" in src
    assert "GraphRiskStats" in src or "external_id" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py::test_janus_search_filters_in_python_not_full_graph_scan_without_tenant tests/test_entity_search.py::test_age_search_cypher_contains_and_tenant -v`

Expected: FAIL — functions missing.

- [ ] **Step 3: Implement twins**

Janus: follow `_list_entity_risk_top_sync` — iterate `g.V().has("tenant_id", tenant_id)`, skip `GraphRiskStats`, skip empty `external_id`, casefold contains on `external_id`, optional label match (`em.get("label")` or list), sort with scored first then `-risk_score` then id, slice to limit. ponytail: full tenant vertex scan; upgrade = mixed index on `external_id`.

AGE: same Cypher shape as `list_entity_risk_top` with `toLower(n.external_id) CONTAINS toLower($q)` and optional label via params JSON. Pass `q` in params_json (never interpolate the needle into the Cypher string). `LIMIT {int(limit)}` is OK because limit is already clamped.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py -v`

Expected: PASS (all Task 1 + Task 2)

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/janusgraph_store.py \
  services/graph-service/src/graph_service/age_client.py \
  services/graph-service/tests/test_entity_search.py
git commit -m "Search graph entities on Janus and AGE with the same contract."
```

---

### Task 3: Frontend domain (URL, filters, merge, stored risk)

**Files:**
- Create: `frontend/src/domain/graphInvestigation.ts`
- Test: `frontend/src/domain/graphInvestigation.test.ts`
- Modify: `frontend/src/api/client.ts` — extend `GraphNode` with optional stored fields (used by the domain module)

**Interfaces:**
- Consumes: `GraphNode`, `GraphEdge`, `pruneSubgraphForLinkView`, `LINK_ANALYSIS_MAX_NODES`
- Produces:
  - `parseGraphWorkspaceParams(sp: URLSearchParams, defaultTenant: string) -> { entityId: string; tenantId: string; depth: number }`
  - `primaryLabel(labels: string[] | undefined) -> string` — `labels[0] || "Custom"`
  - `storedDisplayRisk(node: GraphNode) -> number | null`
  - `typeHistogram(nodes: GraphNode[]) -> Array<{ label: string; count: number }>`
  - `filterWorkspaceNodes(nodes, edges, opts) -> { nodes; edges }`
  - `mergeSubgraphs(seedId, base, extra, maxNodes) -> { nodes; edges; originalNodeCount; prunedNodeCount }`
  - `WorkspaceFilter` type: `{ types: string[] | null; minRisk: number | null; scoredOnly: boolean; growthOnly: boolean }`
  - Growth keep: `relation_growth_1h >= 5 || relation_growth_24h >= 15` (read top-level then `properties`)

`types: null` means all types. `types: ["Person"]` hides others. Unscored stay visible under `minRisk` unless `scoredOnly`. Growth on hides null growth.

Extend `GraphNode`:

```ts
export interface GraphNode {
  id: string;
  labels: string[];
  properties: Record<string, unknown>;
  scored?: boolean;
  risk_score?: number | null;
  risk_factors?: string[] | null;
  relation_count?: number | null;
  relation_growth_1h?: number | null;
  relation_growth_24h?: number | null;
}
```

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/domain/graphInvestigation.test.ts` covering: `entity`/`tenant` aliases; depth clamp 1–5 default 2; type hide; unscored remains at `minRisk=10` unless `scoredOnly`; growth toggle does not treat null as 0; merge keeps seed, no duplicate edges, prune cap 3000; `storedDisplayRisk` null when unscored, `0` when scored 0.

```ts
import { describe, expect, it } from "vitest";
import { LINK_ANALYSIS_MAX_NODES } from "./linkAnalysisGraph";
import {
  filterWorkspaceNodes,
  mergeSubgraphs,
  parseGraphWorkspaceParams,
  storedDisplayRisk,
  typeHistogram,
} from "./graphInvestigation";

const n = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  labels: (extra.labels as string[]) ?? ["Person"],
  properties: {},
  ...extra,
});
const e = (a: string, b: string) => ({ from_id: a, to_id: b, type: "KNOWS" });

describe("parseGraphWorkspaceParams", () => {
  it("reads entity_id / tenant_id / depth", () => {
    const p = parseGraphWorkspaceParams(
      new URLSearchParams("entity_id=a&tenant_id=acme&depth=4"),
      "demo",
    );
    expect(p).toEqual({ entityId: "a", tenantId: "acme", depth: 4 });
  });
  it("accepts entity / tenant aliases", () => {
    const p = parseGraphWorkspaceParams(new URLSearchParams("entity=a&tenant=acme"), "demo");
    expect(p.entityId).toBe("a");
    expect(p.tenantId).toBe("acme");
    expect(p.depth).toBe(2);
  });
  it("clamps depth 1–5", () => {
    expect(parseGraphWorkspaceParams(new URLSearchParams("depth=9"), "demo").depth).toBe(5);
    expect(parseGraphWorkspaceParams(new URLSearchParams("depth=0"), "demo").depth).toBe(1);
  });
});

describe("storedDisplayRisk", () => {
  it("null when unscored", () => {
    expect(storedDisplayRisk(n("a", { scored: false, risk_score: null }))).toBeNull();
  });
  it("0 when scored 0", () => {
    expect(storedDisplayRisk(n("a", { scored: true, risk_score: 0 }))).toBe(0);
  });
});

describe("filterWorkspaceNodes", () => {
  const nodes = [
    n("p", { labels: ["Person"], scored: true, risk_score: 80, relation_growth_1h: 6, relation_growth_24h: 6 }),
    n("d", { labels: ["Device"], scored: false, risk_score: null, relation_growth_1h: null, relation_growth_24h: null }),
    n("c", { labels: ["Person"], scored: true, risk_score: 0, relation_growth_1h: 0, relation_growth_24h: 0 }),
  ];
  const edges = [e("p", "d"), e("p", "c")];

  it("hides other types", () => {
    const r = filterWorkspaceNodes(nodes, edges, {
      types: ["Device"], minRisk: null, scoredOnly: false, growthOnly: false,
    });
    expect(r.nodes.map((x) => x.id)).toEqual(["d"]);
    expect(r.edges).toHaveLength(0);
  });

  it("keeps unscored under minRisk unless scoredOnly", () => {
    const r = filterWorkspaceNodes(nodes, edges, {
      types: null, minRisk: 10, scoredOnly: false, growthOnly: false,
    });
    expect(r.nodes.map((x) => x.id).sort()).toEqual(["d", "p"]);
    const only = filterWorkspaceNodes(nodes, edges, {
      types: null, minRisk: 10, scoredOnly: true, growthOnly: false,
    });
    expect(only.nodes.map((x) => x.id)).toEqual(["p"]);
  });

  it("growth toggle hides null growth", () => {
    const r = filterWorkspaceNodes(nodes, edges, {
      types: null, minRisk: null, scoredOnly: false, growthOnly: true,
    });
    expect(r.nodes.map((x) => x.id)).toEqual(["p"]);
  });
});

describe("mergeSubgraphs", () => {
  it("unions without duplicate edges and keeps seed", () => {
    const r = mergeSubgraphs(
      "seed",
      { nodes: [n("seed"), n("a")], edges: [e("seed", "a")] },
      { nodes: [n("a"), n("b")], edges: [e("seed", "a"), e("a", "b")] },
      10,
    );
    expect(r.nodes.map((x) => x.id).sort()).toEqual(["a", "b", "seed"]);
    expect(r.edges).toHaveLength(2);
    expect(r.prunedNodeCount).toBe(3);
  });

  it("prunes toward seed at cap", () => {
    const extraNodes = Array.from({ length: LINK_ANALYSIS_MAX_NODES + 5 }, (_, i) => n(`n${i}`));
    const extraEdges = extraNodes.map((node) => e("seed", node.id));
    const r = mergeSubgraphs(
      "seed",
      { nodes: [n("seed")], edges: [] },
      { nodes: extraNodes, edges: extraEdges },
      LINK_ANALYSIS_MAX_NODES,
    );
    expect(r.prunedNodeCount).toBe(LINK_ANALYSIS_MAX_NODES);
    expect(r.nodes.some((x) => x.id === "seed")).toBe(true);
  });
});

describe("typeHistogram", () => {
  it("counts primary labels on loaded set", () => {
    const h = typeHistogram([n("a", { labels: ["Person"] }), n("b", { labels: ["Person"] }), n("c", { labels: ["Device"] })]);
    expect(h).toEqual([
      { label: "Person", count: 2 },
      { label: "Device", count: 1 },
    ]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- src/domain/graphInvestigation.test.ts`

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `graphInvestigation.ts`**

`parseGraphWorkspaceParams`: `entity_id` else `entity`; `tenant_id` else `tenant` else `defaultTenant`; depth `Number.parseInt` clamp 1–5 default 2.

`filterWorkspaceNodes`: filter nodes, then edges where both ends remain.

`mergeSubgraphs`: Map nodes by id (extra overwrites same id); edge key `` `${from_id}\0${to_id}\0${type}` ``; then `pruneSubgraphForLinkView(nodes, edges, seedId, maxNodes)`.

`storedDisplayRisk`: if `scored === false` or (`risk_score == null` and no numeric `properties.risk_score` with `scored !== true`) return null when `scored` is false or missing-and-null. Spec: use subgraph top-level fields. Implementation:

```ts
export function storedDisplayRisk(node: GraphNode): number | null {
  if (node.scored === false) return null;
  if (node.scored === true) {
    const v = node.risk_score;
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  }
  const v = node.risk_score;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return null;
}
```

Histogram: sort by count desc, then label asc.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- src/domain/graphInvestigation.test.ts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/domain/graphInvestigation.ts \
  frontend/src/domain/graphInvestigation.test.ts \
  frontend/src/api/client.ts
git commit -m "Add graph workspace URL, filter, and expand-merge helpers."
```

---

### Task 4: OpenAPI, client, mocks

**Files:**
- Modify: `contracts/openapi/graph-service.yaml`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/mockData.ts`

**Interfaces:**
- Consumes: search response shape from Task 1
- Produces:
  - `graph.searchEntities({ tenant_id, q, label?, limit? })`
  - `graph.entityRiskTop({ tenant_id, limit?, min_score? })`
  - `graph.schema(tenantId)` → `{ entity_types: string[] }`
  - `graph.pathExplain` query keys `from_entity_id` / `to_entity_id` (backend names; keep TS args `subject`/`target` mapped)

- [ ] **Step 1: Add OpenAPI path** after `/v1/subgraph`:

```yaml
  /v1/entities/search:
    get:
      operationId: searchEntities
      summary: Find graph nodes by external_id contains and optional label
      parameters:
        - name: tenant_id
          in: query
          required: true
          schema: { type: string }
        - name: q
          in: query
          required: false
          schema: { type: string, maxLength: 256 }
        - name: label
          in: query
          required: false
          schema: { type: string }
        - name: limit
          in: query
          required: false
          schema: { type: integer, default: 20 }
          description: Clamped to 1–50
      responses:
        "200":
          description: Empty list when q is blank; otherwise matching nodes
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/EntitySearchResponse"
```

Components:

```yaml
    EntitySearchHit:
      type: object
      required: [entity_id, tenant_id, labels, scored]
      properties:
        entity_id: { type: string }
        tenant_id: { type: string }
        labels: { type: array, items: { type: string } }
        scored: { type: boolean }
        risk_score: { type: number, nullable: true }
    EntitySearchResponse:
      type: object
      required: [entities]
      properties:
        entities:
          type: array
          items: { $ref: "#/components/schemas/EntitySearchHit" }
```

- [ ] **Step 2: Client methods**

```ts
searchEntities(params: { tenant_id: string; q: string; label?: string; limit?: number }) {
  const q = new URLSearchParams({ tenant_id: params.tenant_id, q: params.q });
  if (params.label) q.set("label", params.label);
  if (params.limit != null) q.set("limit", String(params.limit));
  return request<{ entities: Array<{
    entity_id: string; tenant_id: string; labels: string[]; scored: boolean; risk_score: number | null;
  }> }>(`/api/graph/v1/entities/search?${q}`);
},
entityRiskTop(params: { tenant_id: string; limit?: number; min_score?: number }) {
  const q = new URLSearchParams({ tenant_id: params.tenant_id });
  if (params.limit != null) q.set("limit", String(params.limit));
  if (params.min_score != null) q.set("min_score", String(params.min_score));
  return request<{ entities: Array<{ entity_id: string; labels: string[]; risk_score: number }> }>(
    `/api/graph/v1/analytics/entity-risk/top?${q}`,
  );
},
schema(tenantId: string) {
  return request<{ entity_types: string[] }>(`/api/graph/v1/schema/${encodeURIComponent(tenantId)}`);
},
```

Change `pathExplain` to `q.set("from_entity_id", params.subject)` and `q.set("to_entity_id", params.target)` when target is set.

- [ ] **Step 3: Mocks in `mockData.ts`**

Handle `/api/graph/v1/entities/search` **before** generic `/entities/` tag routes. Empty `q` → `{ entities: [] }`. Otherwise return `fraud_frank` if `q` matches `/frank/i`, with `labels: ["Person"]`, `scored: true`, `risk_score: 72`. Filter by `label` if present.

`/api/graph/v1/analytics/entity-risk/top` **before** the existing entity-risk prefix check (the current `path.includes("/api/graph/v1/analytics/entity-risk")` would swallow `/top`). Add an explicit `/entity-risk/top` branch returning `[{ entity_id: "fraud_frank", labels: ["Person"], risk_score: 72, ... }]`.

`/api/graph/v1/schema/` → `{ entity_types: ["Person","Account","Device","Payment","Email","IP","Address"] }`.

- [ ] **Step 4: Commit**

```bash
git add contracts/openapi/graph-service.yaml frontend/src/api/client.ts frontend/src/api/mockData.ts
git commit -m "Expose graph entity search on OpenAPI, client, and mocks."
```

---

### Task 5: Workspace page, redirect, nav

**Files:**
- Create: `frontend/src/pages/GraphInvestigationPage.tsx`
- Modify: `frontend/src/components/LinkAnalysisForceGraph.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/CommandPalette.tsx`
- Modify: `frontend/src/config/accessModuleCatalog.ts`
- Delete: `frontend/src/pages/GraphExplorer.tsx`
- Delete: `frontend/src/pages/LinkAnalysisPage.tsx`

**Interfaces:**
- Consumes: Task 3 helpers, Task 4 client, `LinkAnalysisForceGraph`, `GraphContextPanel`, `useFailoverPlanes`, `pruneSubgraphAsync`
- Produces: `/graph` workspace; `/graph/link-analysis` redirect preserving query string

- [ ] **Step 1: Force-graph extras**

Add optional `highlightIds?: Set<string>` and `onNodeDoubleClick?: LinkAnalysisNodeSelectHandler`. In `nodeCanvasObject`, if `highlightIds` is non-empty and the node id is in the set, draw a wider stroke (`#60a5fa`). Wire `onNodeRightClick` **not** used — use `onNodeClick` existing; add:

```ts
onNodeDblClick={
  onNodeDoubleClick
    ? (node) => {
        const id = typeof node.id === "string" || typeof node.id === "number" ? String(node.id) : "";
        if (id) onNodeDoubleClick(id, node as LinkAnalysisGraphNode);
      }
    : undefined
}
```

- [ ] **Step 2: Redirect helper in App.tsx**

```tsx
function RedirectLinkAnalysisToGraph() {
  const [params] = useSearchParams();
  const qs = params.toString();
  return <Navigate to={qs ? `/graph?${qs}` : "/graph"} replace />;
}
```

Replace `<Route path="/graph" element={<GraphExplorer />} />` with `GraphInvestigationPage`. Replace link-analysis route with `RedirectLinkAnalysisToGraph`. Drop `LinkAnalysisPage` lazy import. Nav item: `{ to: "/graph", label: "Graph", module: "graph" }` — remove the “Link analysis (2D)” item.

Command palette + accessModuleCatalog: label **Graph**.

- [ ] **Step 3: Implement `GraphInvestigationPage.tsx`**

Layout: CSS grid `140px 1fr 280px` under a top search row (Palantir A). Behavior:

1. `parseGraphWorkspaceParams` from `useSearchParams`; tenant default from `localStorage tarka.tenant_id` else `demo`.
2. If `graphPlaneDisabled`: Explorer failover banner; do not call graph APIs.
3. Empty `entityId`: `graph.entityRiskTop({ tenant_id, limit: 20 })` list; click → `setSearchParams` `{ entity_id, tenant_id, depth }`.
4. Seed load: `graph.subgraph(entityId, tenantId, depth)` → prune → paint via a `Map` of `storedDisplayRisk` per node (do **not** call `entityRisk` / `riskPropagation`). If `originalNodeCount > prunedNodeCount`, show the existing prune note.
5. URL write-back uses `entity_id` / `tenant_id` / `depth` only (never persist the `entity` / `tenant` aliases). Top: typeahead `graph.searchEntities` debounce 200ms + abort/ignore stale; schema chips `graph.schema(tenantId)` set search `label` only; tenant input; depth 1–5.
6. Left: `typeHistogram(loadedNodes)` click sets `filter.types`; min-risk number; scored-only checkbox default off; growth toggle; button “Rings / communities” → `graph.communities` + `graph.fraudRings`; click row sets `highlightIds` to member ids present on canvas.
7. Click node → dossier entity. Double-click / dossier Expand → `graph.subgraph(id, tenant, 1)` → `mergeSubgraphs(seed, current, extra, 3000)`; on failure keep canvas + error banner.
8. Dossier “Path from seed” if selected ≠ seed → `graph.pathExplain({ tenant_id, subject: seed, target: selected, depth: 3 })`; highlight path node ids; on miss set dossier message.
9. Right column always visible: `GraphContextPanel open={Boolean(selectedId)}`.
10. Apply `filterWorkspaceNodes` before passing data to the force-graph.

Reuse Explorer’s `NODE_COLORS` / failover copy. Keep a Mule path link to `/graph/mule-path`.

If schema GET fails, chips = `["Person","Account","Device","Payment","Email","IP","Address"]`.

- [ ] **Step 4: Delete old pages** after App compiles with the new import. Grep `GraphExplorer` / `LinkAnalysisPage` — only App should have referenced them; fix any leftover imports.

- [ ] **Step 5: Run domain tests again + frontend test suite slice**

Run: `cd frontend && npm test -- src/domain/graphInvestigation.test.ts src/domain/linkAnalysisGraph.test.ts src/config/leanNav.test.ts`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/GraphInvestigationPage.tsx \
  frontend/src/components/LinkAnalysisForceGraph.tsx \
  frontend/src/App.tsx \
  frontend/src/components/CommandPalette.tsx \
  frontend/src/config/accessModuleCatalog.ts
git rm frontend/src/pages/GraphExplorer.tsx frontend/src/pages/LinkAnalysisPage.tsx
git commit -m "Replace Graph Explorer and Link Analysis with one investigation workspace."
```

---

### Task 6: Docs

**Files:**
- Modify: `docs/docs/services/graph-service.md`
- Modify: `docs/docs/api-reference.md`

- [ ] **Step 1: Document search**

API reference table (near `POST /v1/entities`): `| \`GET\` | \`/v1/entities/search\` | Graph nodes by id contains + optional label |`

Short section: empty `q` returns `[]`; limit clamp 1–50; `risk_score` null when unscored; does not live-compute risk.

graph-service.md: one subsection under Endpoints matching that contract. Note the SPA `/graph` workspace uses this + stored subgraph risk (no live entity-risk on seed load).

- [ ] **Step 2: Commit**

```bash
git add docs/docs/services/graph-service.md docs/docs/api-reference.md
git commit -m "Document graph entity search for the investigation workspace."
```

---

## Spec coverage

| Spec requirement | Task |
|------------------|------|
| `GET /v1/entities/search` contract | 1, 2, 4, 6 |
| Layout A / `/graph` merge | 5 |
| `/graph/link-analysis` redirect + aliases | 3, 5 |
| Expand merge + prune 3000 | 3, 5 |
| Filters type / min risk / growth / scored-only | 3, 5 |
| Path overlay `from_entity_id`/`to_entity_id` | 4, 5 |
| Stored risk paint, no live entity-risk on seed | 3, 5 |
| Empty state top-N | 4, 5 |
| Schema chips read-only | 5 |
| Rings/communities highlight only | 5 |
| Failover / empty search / keep canvas on expand fail | 5 |
| No new AI tool / no vis-network / mule-path stays | 5 |
| Nav label Graph | 5 |
