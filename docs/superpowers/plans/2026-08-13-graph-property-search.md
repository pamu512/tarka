# Graph Property Search + Identity Resolve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `GET /v1/entities/search` so typing an email/device/IP/phone/card finds the identifier node and neighboring Person/Account/User, and the `/graph` typeahead can seed either row.

**Architecture:** Shared Python match/dedupe/rank in `entity_risk_score.py`. Each graph backend finds direct CONTAINS hits on allowlisted string props, then 1-hop owners from identifier labels. `merge_search_hits` applies label filter after resolve. UI adds a `via` subtitle; click still seeds `hit.entity_id`. No new index, write path, or HTTP hop.

**Tech Stack:** FastAPI graph-service, Cypher (Neo4j/AGE) + Gremlin (Janus), React typeahead, pytest, vitest.

## Global Constraints

- Decision-api / rules remain sole allow/deny. Stored `risk_score` is a feature, not a decision.
- Do not invent graph, nodes, paths, `entity_id`, `via`, or scores when the graph plane is down or `external_id` is blank.
- `0` is a computed clean score. Unscored is `scored: false`, `risk_score: null`.
- Match is case-insensitive CONTAINS on allowlisted **string** props only. Non-strings are ignored (not `toString`-coerced in Python).
- Empty `q` → `{ "entities": [] }` 200, no scan (existing HTTP handler; do not change).
- `label` filters **returned** rows after resolve.
- Limit default 20, clamp 1–50, applied after union + dedupe + label.
- Fan-out: at most 10 owner neighbors per identifier node.
- No Elasticsearch, no `search_keys` on write, no expand/empty-state/dossier changes.
- Parameterized `$q` only. `cypher_search_prop_predicate` may interpolate frozen `SEARCH_PROP_KEYS` (safe identifiers), never user input.
- Janus stays a tenant vertex scan (ponytail: upgrade = mixed index on allowlisted keys).
- CI graph-service: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py -v`
- CI frontend: `cd frontend && npm test -- src/domain/graphInvestigation.test.ts`

## File map

| File | Responsibility |
|------|----------------|
| `services/graph-service/src/graph_service/entity_risk_score.py` | Allowlists, `matched_on_from_props`, `merge_search_hits`, `search_hit_from_node` + `via` |
| `services/graph-service/src/graph_service/neo4j_client.py` | Cypher property CONTAINS + 1-hop owners |
| `services/graph-service/src/graph_service/janusgraph_store.py` | Python property CONTAINS + `both()` owners |
| `services/graph-service/src/graph_service/age_client.py` | AGE Cypher twin of Neo4j |
| `services/graph-service/tests/test_entity_search.py` | Unit + inspect + HTTP tests |
| `contracts/openapi/graph-service.yaml` | `matched_on`, `via` on `EntitySearchHit` |
| `frontend/src/api/client.ts` | `GraphSearchHit` type |
| `frontend/src/domain/graphInvestigation.ts` | `searchHitViaSubtitle` |
| `frontend/src/domain/graphInvestigation.test.ts` | Subtitle tests |
| `frontend/src/pages/GraphInvestigationPage.tsx` | Placeholder + via line |
| `frontend/src/api/mockData.ts` | Email → Person fixture |
| `docs/docs/services/graph-service.md` | Property CONTAINS + resolve |
| `docs/docs/api-reference.md` | Same |

Start on branch `feat/graph-property-search` from current `master`.

---

### Task 1: Shared match, resolve merge, hit shape

**Files:**
- Modify: `services/graph-service/src/graph_service/entity_risk_score.py`
- Test: `services/graph-service/tests/test_entity_search.py`

**Interfaces:**
- Consumes: `stored_risk_view(props) -> dict`, existing `search_hit_from_node`
- Produces:
  - `SEARCH_PROP_KEYS`: `("external_id", "email", "device_id", "address", "line1", "phone", "ip", "user_id", "card_id")`
  - `IDENTIFIER_LABELS`: `frozenset({"Email", "Device", "IP", "Phone", "Address", "Card"})`
  - `OWNER_LABELS`: `frozenset({"Person", "Account", "User"})`
  - `SEARCH_OWNER_FANOUT = 10`
  - `matched_on_from_props(props: dict | None, q: str) -> str | None`
  - `eligible_search_node(entity_id: str, props: dict | None, q: str) -> str | None`
  - `labels_are_identifier(labels: list) -> bool`
  - `labels_are_owner(labels: list) -> bool`
  - `cypher_search_prop_predicate(alias: str = "n") -> str`
  - `cap_identifier_owners(hits: list[dict], fanout: int = SEARCH_OWNER_FANOUT) -> list[dict]`
  - `merge_search_hits(hits: list[dict], *, label: str | None, limit: int) -> list[dict]`
  - `search_hit_from_node(..., *, matched_on: str = "external_id", via: dict | None = None) -> dict` with keys `entity_id`, `tenant_id`, `labels`, `scored`, `risk_score`, `matched_on`, `via`

- [ ] **Step 1: Create the feature branch**

```bash
git checkout master
git checkout -b feat/graph-property-search
```

- [ ] **Step 2: Write the failing tests**

Append to `services/graph-service/tests/test_entity_search.py` (keep existing tests). Add imports:

```python
from graph_service.entity_risk_score import (
    SEARCH_PROP_KEYS,
    cap_identifier_owners,
    eligible_search_node,
    matched_on_from_props,
    merge_search_hits,
    search_hit_from_node,
)
```

Update existing hit tests to assert the new fields:

```python
def test_search_hit_unscored_is_null_not_zero():
    hit = search_hit_from_node("t", "a", ["Account"], {})
    assert hit["scored"] is False
    assert hit["risk_score"] is None
    assert hit["labels"] == ["Account"]
    assert hit["matched_on"] == "external_id"
    assert hit["via"] is None
```

Add:

```python
def test_matched_on_allowlist_order_strings_only():
    props = {"external_id": "user-441", "email": "alice@acme.com", "device_id": 99}
    assert matched_on_from_props(props, "alice@acme") == "email"
    assert matched_on_from_props(props, "user-441") == "external_id"
    assert matched_on_from_props(props, "99") is None
    assert matched_on_from_props(props, "") is None


def test_eligible_skips_blank_external_id():
    assert eligible_search_node("", {"email": "alice@acme.com"}, "alice") is None
    assert eligible_search_node("  ", {"email": "alice@acme.com"}, "alice") is None
    assert eligible_search_node("e1", {"email": "alice@acme.com"}, "alice") == "email"


def test_merge_resolve_person_first_keeps_email():
    email = search_hit_from_node(
        "t", "alice@acme.com", ["Email"], {"email": "alice@acme.com"},
        matched_on="email", via=None,
    )
    person = search_hit_from_node(
        "t", "user-441", ["Person"], {},
        matched_on="email",
        via={"entity_id": "alice@acme.com", "labels": ["Email"]},
    )
    rows = merge_search_hits([email, person], label=None, limit=20)
    assert [h["entity_id"] for h in rows] == ["user-441", "alice@acme.com"]
    assert rows[0]["via"]["entity_id"] == "alice@acme.com"
    assert rows[1]["via"] is None


def test_merge_label_chip_after_resolve():
    email = search_hit_from_node(
        "t", "alice@acme.com", ["Email"], {}, matched_on="email", via=None,
    )
    person = search_hit_from_node(
        "t", "user-441", ["Person"], {},
        matched_on="email",
        via={"entity_id": "alice@acme.com", "labels": ["Email"]},
    )
    only_p = merge_search_hits([email, person], label="Person", limit=20)
    assert [h["entity_id"] for h in only_p] == ["user-441"]
    only_e = merge_search_hits([email, person], label="Email", limit=20)
    assert [h["entity_id"] for h in only_e] == ["alice@acme.com"]
    assert merge_search_hits([email, person], label="Merchant", limit=20) == []


def test_merge_dedupe_keeps_via():
    direct = search_hit_from_node(
        "t", "user-441", ["Person"], {"email": "alice@acme.com"},
        matched_on="email", via=None,
    )
    via_hit = search_hit_from_node(
        "t", "user-441", ["Person"], {},
        matched_on="email",
        via={"entity_id": "alice@acme.com", "labels": ["Email"]},
    )
    rows = merge_search_hits([direct, via_hit], label=None, limit=20)
    assert len(rows) == 1
    assert rows[0]["entity_id"] == "user-441"
    assert rows[0]["via"]["entity_id"] == "alice@acme.com"


def test_cap_identifier_owners_fanout_10():
    ident = "dev-1"
    owners = [
        search_hit_from_node(
            "t", f"u-{i:02d}", ["User"], {},
            matched_on="device_id",
            via={"entity_id": ident, "labels": ["Device"]},
        )
        for i in range(12)
    ]
    capped = cap_identifier_owners(owners)
    assert len(capped) == 10
    merged = merge_search_hits(
        [search_hit_from_node("t", ident, ["Device"], {}, matched_on="device_id", via=None)]
        + capped,
        label=None,
        limit=50,
    )
    assert len([h for h in merged if "User" in h["labels"]]) == 10
    assert any(h["entity_id"] == ident for h in merged)


def test_merge_unscored_sorts_after_scored():
    a = search_hit_from_node("t", "z-user", ["User"], {}, matched_on="email")
    b = search_hit_from_node(
        "t",
        "a-user",
        ["User"],
        {"risk_computed_at": "2026-08-13T00:00:00Z", "risk_score": 0},
        matched_on="email",
    )
    rows = merge_search_hits([a, b], label=None, limit=20)
    assert [h["entity_id"] for h in rows] == ["a-user", "z-user"]
    assert rows[0]["risk_score"] == 0
    assert rows[1]["risk_score"] is None


def test_cypher_predicate_uses_frozen_keys_not_q():
    from graph_service.entity_risk_score import cypher_search_prop_predicate
    src = cypher_search_prop_predicate("n")
    assert "n.email" in src
    assert "n.device_id" in src
    assert "n.line1" in src
    assert "n.card_id" in src
    assert "toLower($q)" in src
    assert "alice" not in src
    for key in SEARCH_PROP_KEYS:
        assert f"n.{key}" in src
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py::test_matched_on_allowlist_order_strings_only tests/test_entity_search.py::test_merge_resolve_person_first_keeps_email -v`

Expected: FAIL — `matched_on_from_props` / `merge_search_hits` not defined (or `matched_on` missing from hit).

- [ ] **Step 4: Implement helpers**

In `entity_risk_score.py`, after `clamp_search_limit`, replace `search_hit_from_node` and add:

```python
SEARCH_PROP_KEYS = (
    "external_id",
    "email",
    "device_id",
    "address",
    "line1",
    "phone",
    "ip",
    "user_id",
    "card_id",
)
IDENTIFIER_LABELS = frozenset({"Email", "Device", "IP", "Phone", "Address", "Card"})
OWNER_LABELS = frozenset({"Person", "Account", "User"})
SEARCH_OWNER_FANOUT = 10


def matched_on_from_props(props: dict[str, Any] | None, q: str) -> str | None:
    needle = str(q or "").casefold()
    if not needle:
        return None
    bag = props or {}
    for key in SEARCH_PROP_KEYS:
        val = bag.get(key)
        if isinstance(val, str) and needle in val.casefold():
            return key
    return None


def eligible_search_node(entity_id: str, props: dict[str, Any] | None, q: str) -> str | None:
    eid = str(entity_id or "").strip()
    if not eid:
        return None
    bag = dict(props or {})
    bag.setdefault("external_id", eid)
    return matched_on_from_props(bag, q)


def labels_are_identifier(labels: list) -> bool:
    return bool(IDENTIFIER_LABELS.intersection(str(x) for x in (labels or [])))


def labels_are_owner(labels: list) -> bool:
    return bool(OWNER_LABELS.intersection(str(x) for x in (labels or [])))


def cypher_search_prop_predicate(alias: str = "n") -> str:
    # ponytail: interpolates frozen SEARCH_PROP_KEYS only; $q stays parameterized.
    parts: list[str] = []
    for key in SEARCH_PROP_KEYS:
        parts.append(
            f"({alias}.{key} IS NOT NULL AND {alias}.{key} = toString({alias}.{key}) "
            f"AND toLower({alias}.{key}) CONTAINS toLower($q))"
        )
    return " OR ".join(parts)


def _prop_rank(key: str) -> int:
    try:
        return SEARCH_PROP_KEYS.index(key)
    except ValueError:
        return len(SEARCH_PROP_KEYS)


def cap_identifier_owners(
    hits: list[dict[str, Any]], fanout: int = SEARCH_OWNER_FANOUT
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for hit in hits:
        via = hit.get("via") or {}
        via_id = str(via.get("entity_id") or "")
        n = counts.get(via_id, 0)
        if n >= fanout:
            continue
        counts[via_id] = n + 1
        out.append(hit)
    return out


def _prefer_search_hit(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a_owner = labels_are_owner(a.get("labels") or [])
    b_owner = labels_are_owner(b.get("labels") or [])
    if b_owner and not a_owner:
        base, other = b, a
    else:
        base, other = a, b
    out = dict(base)
    out["via"] = base.get("via") or other.get("via")
    ma = str(base.get("matched_on") or "")
    mb = str(other.get("matched_on") or "")
    out["matched_on"] = ma if _prop_rank(ma) <= _prop_rank(mb) else mb
    return out


def merge_search_hits(
    hits: list[dict[str, Any]],
    *,
    label: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for hit in hits:
        eid = str(hit.get("entity_id") or "")
        if not eid:
            continue
        prev = by_id.get(eid)
        by_id[eid] = hit if prev is None else _prefer_search_hit(prev, hit)
    rows = list(by_id.values())
    if label:
        rows = [h for h in rows if label in [str(x) for x in (h.get("labels") or [])]]

    def sort_key(h: dict[str, Any]) -> tuple:
        owner = labels_are_owner(h.get("labels") or [])
        scored = bool(h.get("scored"))
        risk = h.get("risk_score")
        risk_sort = -float(risk) if scored and isinstance(risk, (int, float)) else 0.0
        return (not owner, 0 if scored else 1, risk_sort, str(h.get("entity_id") or ""))

    rows.sort(key=sort_key)
    return rows[: int(limit)]


def search_hit_from_node(
    tenant_id: str,
    entity_id: str,
    labels: list,
    props: dict[str, Any] | None,
    *,
    matched_on: str = "external_id",
    via: dict[str, Any] | None = None,
) -> dict[str, Any]:
    view = stored_risk_view(props)
    labs = [str(x) for x in (labels or [])]
    return {
        "entity_id": str(entity_id),
        "tenant_id": str(tenant_id),
        "labels": labs,
        "scored": bool(view["scored"]),
        "risk_score": view["risk_score"],
        "matched_on": matched_on,
        "via": via,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py -v`

Expected: PASS for the new unit tests. Neo4j/Janus/AGE inspect tests still pass (they only check source tokens). HTTP tests still pass.

- [ ] **Step 6: Commit**

```bash
git add services/graph-service/src/graph_service/entity_risk_score.py services/graph-service/tests/test_entity_search.py
git commit -m "Add graph search match, resolve merge, and via hit fields."
```

---

### Task 2: Neo4j property CONTAINS + 1-hop owners

**Files:**
- Modify: `services/graph-service/src/graph_service/neo4j_client.py` (`search_entities`)
- Test: `services/graph-service/tests/test_entity_search.py`

**Interfaces:**
- Consumes: Task 1 helpers (`cypher_search_prop_predicate`, `eligible_search_node`, `labels_are_identifier`, `labels_are_owner`, `cap_identifier_owners`, `merge_search_hits`, `OWNER_LABELS`, `clamp_search_limit`, `search_hit_from_node`)
- Produces: `async search_entities(tenant_id: str, q: str, label: str | None = None, limit: int = 20) -> list[dict]` — property CONTAINS, then 1-hop owners, then merge. No Cypher `LIMIT` on the match (slice in `merge_search_hits`). `label` is not in the MATCH WHERE.

- [ ] **Step 1: Extend inspect tests**

Replace `test_neo4j_search_cypher_is_parameterized_contains` with:

```python
def test_neo4j_search_cypher_is_parameterized_contains():
    src = inspect.getsource(neo4j_client.search_entities)
    assert "CONTAINS" in src
    assert "$q" in src
    assert "$tenant_id" in src
    assert "GraphRiskStats" in src
    assert "toLower" in src
    assert "email" in src
    assert "merge_search_hits" in src
    assert "--(m)" in src or "-- (m)" in src
    assert "IN $ids" in src or "IN $ident_ids" in src
    assert "f\"{q}" not in src
    assert "f'{q}" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py::test_neo4j_search_cypher_is_parameterized_contains -v`

Expected: FAIL — `merge_search_hits` / `--(m)` not in `search_entities` source.

- [ ] **Step 3: Replace `search_entities` in `neo4j_client.py`**

Update the import from `entity_risk_score` to include the Task 1 names. Replace `search_entities` with:

```python
async def search_entities(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    from .entity_risk_score import (
        OWNER_LABELS,
        cap_identifier_owners,
        clamp_search_limit,
        cypher_search_prop_predicate,
        eligible_search_node,
        labels_are_identifier,
        labels_are_owner,
        merge_search_hits,
    )

    limit = clamp_search_limit(limit)
    pred = cypher_search_prop_predicate("n")
    driver = await get_driver()
    match_cypher = f"""
    MATCH (n {{tenant_id: $tenant_id}})
    WHERE NOT n:GraphRiskStats
      AND n.external_id IS NOT NULL AND n.external_id <> ''
      AND ({pred})
    RETURN n.external_id AS entity_id,
           labels(n) AS labels,
           properties(n) AS props
    """
    async with driver.session() as session:
        result = await session.run(match_cypher, tenant_id=tenant_id, q=q)
        rows = await result.data()
    directs: list[dict[str, Any]] = []
    ident_ids: list[str] = []
    ident_meta: dict[str, dict[str, Any]] = {}
    for rec in rows or []:
        if not rec:
            continue
        eid = str(rec.get("entity_id") or "").strip()
        labs = rec.get("labels") or []
        if not isinstance(labs, list):
            labs = list(labs)
        props = rec.get("props") or {}
        if not isinstance(props, dict):
            props = dict(props)
        matched = eligible_search_node(eid, props, q)
        if not matched:
            continue
        hit = search_hit_from_node(
            tenant_id, eid, labs, props, matched_on=matched, via=None
        )
        directs.append(hit)
        if labels_are_identifier(labs):
            ident_ids.append(eid)
            ident_meta[eid] = hit
    owners: list[dict[str, Any]] = []
    if ident_ids:
        owner_cypher = """
        MATCH (n {tenant_id: $tenant_id})--(m)
        WHERE n.external_id IN $ids
          AND NOT m:GraphRiskStats
          AND m.external_id IS NOT NULL AND m.external_id <> ''
          AND any(l IN labels(m) WHERE l IN $owner_labels)
        RETURN n.external_id AS via_id,
               m.external_id AS entity_id,
               labels(m) AS labels,
               properties(m) AS props
        ORDER BY m.external_id ASC
        """
        async with driver.session() as session:
            result = await session.run(
                owner_cypher,
                tenant_id=tenant_id,
                ids=ident_ids,
                owner_labels=list(OWNER_LABELS),
            )
            orows = await result.data()
        raw_owners: list[dict[str, Any]] = []
        for rec in orows or []:
            if not rec:
                continue
            ident = ident_meta.get(str(rec.get("via_id") or ""))
            if not ident:
                continue
            eid = str(rec.get("entity_id") or "").strip()
            labs = rec.get("labels") or []
            if not isinstance(labs, list):
                labs = list(labs)
            if not eid or not labels_are_owner(labs):
                continue
            props = rec.get("props") or {}
            if not isinstance(props, dict):
                props = dict(props)
            raw_owners.append(
                search_hit_from_node(
                    tenant_id,
                    eid,
                    labs,
                    props,
                    matched_on=ident["matched_on"],
                    via={"entity_id": ident["entity_id"], "labels": ident["labels"]},
                )
            )
        owners = cap_identifier_owners(raw_owners)
    return merge_search_hits(directs + owners, label=label, limit=limit)
```

Do not put `$label` in MATCH WHERE. Do not interpolate `q` into the f-string (`pred` is frozen keys only).

- [ ] **Step 4: Run tests**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/graph-service/src/graph_service/neo4j_client.py services/graph-service/tests/test_entity_search.py
git commit -m "Search Neo4j entities by allowlisted properties and owner neighbors."
```

---

### Task 3: Janus and AGE twins

**Files:**
- Modify: `services/graph-service/src/graph_service/janusgraph_store.py` (`search_entities`)
- Modify: `services/graph-service/src/graph_service/age_client.py` (`search_entities`)
- Test: `services/graph-service/tests/test_entity_search.py`

**Interfaces:**
- Consumes: same Task 1 helpers as Neo4j
- Produces: same `search_entities(...)` contract as Neo4j

- [ ] **Step 1: Extend inspect tests**

Replace the Janus/AGE inspect tests with:

```python
def test_janus_search_filters_in_python_not_full_graph_scan_without_tenant():
    src = inspect.getsource(janusgraph_store.search_entities)
    assert "tenant_id" in src
    assert "GraphRiskStats" in src
    assert "eligible_search_node" in src
    assert "merge_search_hits" in src
    assert "both()" in src
    assert "search_hit_from_node" in src


def test_age_search_cypher_contains_and_tenant():
    src = inspect.getsource(age_client.search_entities)
    assert "CONTAINS" in src or "contains" in src
    assert "tenant_id" in src
    assert "$q" in src or "$tenant_id" in src
    assert "merge_search_hits" in src
    assert "GraphRiskStats" in src or "external_id" in src
    assert "f\"{q}" not in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py::test_janus_search_filters_in_python_not_full_graph_scan_without_tenant tests/test_entity_search.py::test_age_search_cypher_contains_and_tenant -v`

Expected: FAIL — `merge_search_hits` / `both()` missing.

- [ ] **Step 3: Replace Janus `search_entities`**

Keep the tenant `g.V().has("tenant_id", tenant_id).toList()` scan (ponytail: upgrade = mixed index). Replace the body:

```python
async def search_entities(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    from .entity_risk_score import (
        cap_identifier_owners,
        clamp_search_limit,
        eligible_search_node,
        labels_are_identifier,
        labels_are_owner,
        merge_search_hits,
    )

    limit = clamp_search_limit(limit)
    needle = str(q or "")

    def _search_entities_sync() -> list[dict[str, Any]]:
        g = get_traversal_source()
        directs: list[dict[str, Any]] = []
        ident_vids: list[tuple[str, dict[str, Any], Any]] = []
        for v in g.V().has("tenant_id", tenant_id).toList():
            if str(getattr(v, "label", "") or "") == "GraphRiskStats":
                continue
            try:
                em = dict(g.V(v).elementMap().next())
            except StopIteration:
                continue
            eid = str(em.get("external_id") or "").strip()
            raw_lbl = em.get("label")
            if isinstance(raw_lbl, list):
                labels = [str(x) for x in raw_lbl] if raw_lbl else ["Custom"]
            else:
                labels = [str(raw_lbl or "Custom")]
            props = {k: val for k, val in em.items() if k not in ("id", "label")}
            matched = eligible_search_node(eid, props, needle)
            if not matched:
                continue
            hit = search_hit_from_node(
                tenant_id, eid, labels, props, matched_on=matched, via=None
            )
            directs.append(hit)
            if labels_are_identifier(labels):
                ident_vids.append((eid, hit, v))
        raw_owners: list[dict[str, Any]] = []
        for _eid, ident, v in ident_vids:
            for nv in g.V(v).both().toList():
                try:
                    em = dict(g.V(nv).elementMap().next())
                except StopIteration:
                    continue
                oid = str(em.get("external_id") or "").strip()
                raw_lbl = em.get("label")
                if isinstance(raw_lbl, list):
                    olabels = [str(x) for x in raw_lbl] if raw_lbl else ["Custom"]
                else:
                    olabels = [str(raw_lbl or "Custom")]
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
        owners = cap_identifier_owners(raw_owners)
        return merge_search_hits(directs + owners, label=label, limit=limit)

    return await run_in_gremlin_thread(_search_entities_sync)
```

Sort owners by `entity_id` before cap if the Gremlin order is unstable: after building `raw_owners`, `raw_owners.sort(key=lambda h: str(h.get("entity_id") or ""))` then cap.

- [ ] **Step 4: Replace AGE `search_entities`**

Mirror Neo4j: match query uses `cypher_search_prop_predicate("n")` inside the `$$` block; params still `json.dumps({"tenant_id", "q"})`. Do not interpolate `q`. Drop `LIMIT {int(limit)}` from the match query. Return `properties(n)` (or equivalent) so Python can run `eligible_search_node`.

Owner query pattern (same 1-hop as existing `list_one_hop_ids`):

```
MATCH (n {tenant_id: $tenant_id})-[r]-(m)
WHERE n.external_id IN $ids
  AND NOT m:GraphRiskStats
  AND m.external_id IS NOT NULL
```

Pass `ids` and `owner_labels` in the JSON params. Map rows through `search_hit_from_node` + `cap_identifier_owners` + `merge_search_hits` exactly as Neo4j.

If AGE rejects `IN $ids`, loop `list_one_hop_ids` per identifier (already in this file) then load each owner node’s labels/props; still cap at 10 per via.

- [ ] **Step 5: Run tests**

Run: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_entity_search.py -v`

Expected: PASS (including HTTP empty-`q` still `store.assert_not_called()`).

- [ ] **Step 6: Commit**

```bash
git add services/graph-service/src/graph_service/janusgraph_store.py services/graph-service/src/graph_service/age_client.py services/graph-service/tests/test_entity_search.py
git commit -m "Resolve identifier neighbors in Janus and AGE entity search."
```

---

### Task 4: OpenAPI + service docs

**Files:**
- Modify: `contracts/openapi/graph-service.yaml`
- Modify: `docs/docs/services/graph-service.md`
- Modify: `docs/docs/api-reference.md`

**Interfaces:**
- Consumes: hit shape from Task 1
- Produces: `EntitySearchHit` with required `matched_on`; `via` nullable object `{ entity_id, labels }`

- [ ] **Step 1: Update OpenAPI `EntitySearchHit`**

In `contracts/openapi/graph-service.yaml`:

- Change path summary from “external_id contains” to “allowlisted property contains and optional identity resolve”.
- Replace `EntitySearchHit` with:

```yaml
    EntitySearchHit:
      type: object
      required: [entity_id, tenant_id, labels, scored, matched_on]
      properties:
        entity_id: { type: string }
        tenant_id: { type: string }
        labels: { type: array, items: { type: string } }
        scored: { type: boolean }
        risk_score: { type: number, nullable: true }
        matched_on:
          type: string
          enum: [external_id, email, device_id, address, line1, phone, ip, user_id, card_id]
        via:
          type: object
          nullable: true
          required: [entity_id, labels]
          properties:
            entity_id: { type: string }
            labels: { type: array, items: { type: string } }
```

- [ ] **Step 2: Update docs**

`docs/docs/services/graph-service.md` Search Entities section: match is case-insensitive CONTAINS on `external_id`, `email`, `device_id`, `address`, `line1`, `phone`, `ip`, `user_id`, `card_id`. Identifier labels `Email`/`Device`/`IP`/`Phone`/`Address`/`Card` also return 1-hop `Person`/`Account`/`User` (cap 10). `label` applies after resolve. Include `matched_on` and `via` in the sample JSON.

`docs/docs/api-reference.md`: table row near search → `Graph nodes by property contains + identity resolve`. Body sample includes a Person with `"via": { "entity_id": "alice@acme.com", "labels": ["Email"] }` and `"matched_on": "email"`.

- [ ] **Step 3: Commit**

```bash
git add contracts/openapi/graph-service.yaml docs/docs/services/graph-service.md docs/docs/api-reference.md
git commit -m "Document graph search property match and identity resolve."
```

---

### Task 5: Typeahead via subtitle + mock email fixture

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/domain/graphInvestigation.ts`
- Modify: `frontend/src/domain/graphInvestigation.test.ts`
- Modify: `frontend/src/pages/GraphInvestigationPage.tsx`
- Modify: `frontend/src/api/mockData.ts`

**Interfaces:**
- Consumes: `via` / `matched_on` from search hits
- Produces:
  - `export type GraphSearchHit` in `client.ts`
  - `searchHitViaSubtitle(via: GraphSearchHit["via"]) => string | null`
  - Placeholder `Id, email, device, IP…`
  - Mock: `q` matching `/alice@acme/i` returns Person `user-441` (via Email) then Email `alice@acme.com`
  - Click remains `selectEntity(hit.entity_id, …)` (no extra request)

- [ ] **Step 1: Write failing subtitle tests**

In `frontend/src/domain/graphInvestigation.test.ts` add import `searchHitViaSubtitle` and:

```typescript
describe("searchHitViaSubtitle", () => {
  it("formats via label and id", () => {
    expect(searchHitViaSubtitle({ entity_id: "alice@acme.com", labels: ["Email"] })).toBe(
      "via Email alice@acme.com",
    );
  });
  it("null when via missing", () => {
    expect(searchHitViaSubtitle(null)).toBeNull();
    expect(searchHitViaSubtitle(undefined)).toBeNull();
    expect(searchHitViaSubtitle({ entity_id: "", labels: ["Email"] })).toBeNull();
  });
  it("falls back to Custom when labels empty", () => {
    expect(searchHitViaSubtitle({ entity_id: "dev-1", labels: [] })).toBe("via Custom dev-1");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- src/domain/graphInvestigation.test.ts`

Expected: FAIL — `searchHitViaSubtitle` is not exported.

- [ ] **Step 3: Types + helper + page + mock**

In `frontend/src/api/client.ts`, above `export const graph`, add:

```typescript
export type GraphSearchMatchedOn =
  | "external_id"
  | "email"
  | "device_id"
  | "address"
  | "line1"
  | "phone"
  | "ip"
  | "user_id"
  | "card_id";

export type GraphSearchHit = {
  entity_id: string;
  tenant_id: string;
  labels: string[];
  scored: boolean;
  risk_score: number | null;
  matched_on?: GraphSearchMatchedOn;
  via?: { entity_id: string; labels: string[] } | null;
};
```

Change `searchEntities` to `request<{ entities: GraphSearchHit[] }>(...)`.

In `graphInvestigation.ts`:

```typescript
export function searchHitViaSubtitle(
  via: { entity_id: string; labels?: string[] | null } | null | undefined,
): string | null {
  const id = via?.entity_id?.trim() ?? "";
  if (!id) return null;
  const kind = via?.labels?.[0] || "Custom";
  return `via ${kind} ${id}`;
}
```

In `GraphInvestigationPage.tsx`:

- Import `type GraphSearchHit` and `searchHitViaSubtitle`.
- Type `searchHits` as `GraphSearchHit[]`.
- Placeholder: `Id, email, device, IP…`
- Inside the button, keep `onClick={() => selectEntity(hit.entity_id, hit.tenant_id || tenantId)}`.
- After the existing line-1 spans, render:

```tsx
{searchHitViaSubtitle(hit.via) ? (
  <div className="text-[11px] text-gray-500 mt-0.5">{searchHitViaSubtitle(hit.via)}</div>
) : null}
```

(or assign `const viaLine = searchHitViaSubtitle(hit.via)` once per row).

Missing `via` / `matched_on`: one line; do not invent a subtitle.

In `mockData.ts` search handler, **before** the frank check:

```typescript
    if (/alice@acme/i.test(q)) {
      const tenant = u.searchParams.get("tenant_id") ?? "demo";
      const label = u.searchParams.get("label");
      const person = {
        entity_id: "user-441",
        tenant_id: tenant,
        labels: ["Person"],
        scored: false,
        risk_score: null,
        matched_on: "email",
        via: { entity_id: "alice@acme.com", labels: ["Email"] },
      };
      const email = {
        entity_id: "alice@acme.com",
        tenant_id: tenant,
        labels: ["Email"],
        scored: false,
        risk_score: null,
        matched_on: "email",
        via: null,
      };
      const entities = [person, email].filter((h) => !label || h.labels.includes(label));
      return { entities };
    }
```

Keep the existing frank fixture; add `matched_on: "external_id"` and `via: null` on it.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- src/domain/graphInvestigation.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/domain/graphInvestigation.ts frontend/src/domain/graphInvestigation.test.ts frontend/src/pages/GraphInvestigationPage.tsx frontend/src/api/mockData.ts
git commit -m "Show identity-resolve subtitles on graph search typeahead."
```

---

## Self-review (spec coverage)

| Spec requirement | Task |
|------------------|------|
| Allowlisted CONTAINS, strings only | 1 (`matched_on_from_props`) + 2/3 Cypher/Janus |
| Skip blank `external_id` | 1 `eligible_search_node` + backends |
| Identifier → 1-hop Person/Account/User, cap 10 | 1 `cap_identifier_owners` + 2/3 hop queries |
| Dedupe keep via; owner rank; unscored last | 1 `merge_search_hits` |
| `label` after resolve | 1 merge + 2/3 omit MATCH label |
| Hit `matched_on` + `via` | 1 + 4 OpenAPI + 5 types |
| Typeahead both rows, click seeds that id | 5 |
| Empty `q` no scan | unchanged HTTP; Task 3 re-runs it |
| Parameterized `$q`; Janus tenant scan | 2/3 inspect tests |
| Docs | 4 |
| Out of scope (ES, expand prune, empty-state, invent ids) | no tasks |

No TBD/TODO. Names: `merge_search_hits`, `searchHitViaSubtitle`, `GraphSearchHit` used consistently.
