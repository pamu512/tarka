# Leftover station + Hunt production bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship production leftover ops at 3.8 and production Hunt at 4.0 so the demo inherits those numbers only when it walks the same path.

**Architecture:** Work arrives on a thin leftover list (case-api). Work happens on Hunt. Evaluate mint labels leftovers `origin:evaluate`. Hunt search is SQL `search_keys` (no AGE `MATCH (n)`). Unknown `last_outcome` is labeled, never painted as allow. Graph lag is a banner against `graph.latestEvaluate`.

**Tech Stack:** FastAPI case-api + graph-service, SQLAlchemy/alembic, Postgres (AGE + `search_keys`), React desk, pytest TestClient, vitest.

**Spec:** `docs/superpowers/specs/2026-08-31-leftover-hunt-production-design.md`

## Global Constraints

- Decision-api / Rust packs remain sole allow/deny. Evaluate never waits on graph.
- ALLOW and `flag` never mint a leftover. Review is residual.
- Home stays `/graph` when graph is on. `/cases` stays hidden in lean nav.
- Do not reuse `assigned_team` / `default_owner` for claim.
- AGE production search is SQL only. Do not run `MATCH (n)` on that path. Do not use AGE `[*1..n]` or Cypher GIN.
- Keep `HUNT_HIERARCHY_EXPAND_CAP = 8`. If N > 8, show **Showing 8 of N instruments**.
- Missing `last_outcome` is **unknown**, never sorted or painted as allow.
- Do not turn `CASE_CREATE_ON_DENY_REVIEW` on for lite by default. The mint path must work and be tested.
- No fat Cases.tsx, no-code builder, FinCEN, consortium, next-unassigned, or QA sampling.
- Do not commit unless the user asks (overrides frequent-commit habit).
- CI case-api: `cd services/case-api && PYTHONPATH=src:.:../shared pytest tests/test_leftovers.py tests/test_object_act.py -q`
- CI decision-api: `cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_decision_outcome.py -q`
- CI graph-service: `cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_search_keys.py tests/test_entity_search.py -q`
- CI frontend: `cd frontend && npm test -- --run src/config/leanNav.test.ts src/pages/Leftovers.test.tsx src/domain/graphInvestigation.test.ts src/components/GraphContextPanel.test.tsx`

## File map

| File | Responsibility |
|------|----------------|
| `services/case-api/src/case_api/models.py` | `claimed_by`, `claimed_at`, `last_outcome`, `last_act` on `Case` |
| `services/case-api/alembic/versions/20260831_010_leftover_claim.py` | Postgres columns |
| `services/case-api/src/case_api/schemas.py` | Create labels/outcome; act `hold\|release\|resolve`; leftover DTOs |
| `services/case-api/src/case_api/leftover.py` | Predicate, origin, claim, list row |
| `services/case-api/src/case_api/main.py` | Create labels; leftovers list/claim; act hold/release/resolve |
| `services/case-api/tests/test_leftovers.py` | Predicate, mint, claim 200/409, Hold no-steal, resolve, ALLOW/flag |
| `services/decision-api/src/decision_api/decision_outcome.py` | Mint body includes `origin:evaluate` + `last_outcome` |
| `frontend/src/config/leanNav.ts` | `/leftovers` in lean; visible only when graph is on |
| `frontend/src/pages/Leftovers.tsx` | Thin table. Row click claims then `/graph?entity_id=` |
| `frontend/src/App.tsx` | Route + nav item |
| `frontend/src/api/client.ts` | `listLeftovers`, `claimLeftover`; act actions expand |
| `services/graph-service/src/graph_service/search_keys.py` | Table ensure, upsert, prefix search, outcome rank |
| `services/graph-service/src/graph_service/age_client.py` | After Person/Device upsert, write keys; search = SQL |
| `services/graph-service/src/graph_service/graph_runtime.py` | Fail-soft search upsert after any backend upsert |
| `services/graph-service/src/graph_service/main.py` | Empty/`q`<2 → no scan, `truncated: false` |
| `frontend/src/domain/graphInvestigation.ts` | `lastOutcomeLabel`, instrument cap+total, unknown paint, lag predicate |
| `frontend/src/components/GraphContextPanel.tsx` | Header outcome/unknown, lag banner, 8 of N, resolve/release |
| `frontend/src/pages/GraphInvestigationPage.tsx` | Typeahead outcome; canvas unknown color |

---

### Task 1: Leftover columns + predicate + evaluate mint

**Files:**
- Create: `services/case-api/src/case_api/leftover.py`
- Create: `services/case-api/alembic/versions/20260831_010_leftover_claim.py`
- Create: `services/case-api/tests/test_leftovers.py`
- Modify: `services/case-api/src/case_api/models.py`
- Modify: `services/case-api/src/case_api/schemas.py` (`CreateCaseRequest`)
- Modify: `services/case-api/src/case_api/main.py` (`create_case`)
- Modify: `services/decision-api/src/decision_api/decision_outcome.py`
- Test: `services/decision-api/tests/test_decision_outcome.py`

**Interfaces:**
- Consumes: `Case.labels`, `Case.status`, `Case.entity_id`
- Produces:
  - `Case.claimed_by: str | None`, `claimed_at: datetime | None`, `last_outcome: str | None`, `last_act: str | None`
  - `is_leftover(case) -> bool`
  - `leftover_origin(labels) -> "hold" | "evaluate" | "both"`
  - `CreateCaseRequest.labels: list[str] = []`, `last_outcome: str | None = None`
  - `maybe_create_case_for_outcome` POST body includes `labels: ["origin:evaluate"]` and `last_outcome: ctx.decision`

- [ ] **Step 1: Write the failing tests**

`services/case-api/tests/test_leftovers.py` (pure predicate first; HTTP later in Task 2):

```python
from types import SimpleNamespace

from case_api.leftover import is_leftover, leftover_origin


def _case(**kw):
    base = dict(status="open", entity_id="buyer-1", labels=["act:hold"])
    base.update(kw)
    return SimpleNamespace(**base)


def test_leftover_hold_open():
    assert is_leftover(_case()) is True
    assert leftover_origin(["act:hold"]) == "hold"


def test_leftover_evaluate_open():
    assert is_leftover(_case(labels=["origin:evaluate"])) is True
    assert leftover_origin(["origin:evaluate"]) == "evaluate"


def test_leftover_both():
    assert leftover_origin(["act:hold", "origin:evaluate"]) == "both"


def test_not_leftover_blank_entity_or_allow_case_or_closed():
    assert is_leftover(_case(entity_id="")) is False
    assert is_leftover(_case(entity_id="  ")) is False
    assert is_leftover(_case(labels=[])) is False
    assert is_leftover(_case(status="resolved", labels=["act:hold"])) is False
    assert is_leftover(_case(status="closed", labels=["origin:evaluate"])) is False
```

`services/decision-api/tests/test_decision_outcome.py` — add:

```python
def test_maybe_create_case_sends_origin_evaluate_and_last_outcome():
    import asyncio
    from types import SimpleNamespace
    from decision_api.decision_outcome import maybe_create_case_for_outcome, DecisionOutcomeContext

    captured = {}

    class _Http:
        async def post(self, url, *, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return SimpleNamespace(status_code=201)

    ctx = DecisionOutcomeContext(
        trace_id="tr-deny",
        tenant_id="ten",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=90.0,
        tags=[],
    )
    asyncio.run(
        maybe_create_case_for_outcome(
            http=_Http(),
            case_api_url="http://case.test",
            ctx=ctx,
            headers={},
        )
    )
    assert captured["json"]["labels"] == ["origin:evaluate"]
    assert captured["json"]["last_outcome"] == "deny"
```

Keep existing `test_allow_does_not_create_case`. Add the same enqueue assert for `decision="flag"` (must not enqueue mint).

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/case-api && PYTHONPATH=src:.:../shared pytest tests/test_leftovers.py -q
cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_decision_outcome.py::test_maybe_create_case_sends_origin_evaluate_and_last_outcome -q
```

Expected: FAIL — `case_api.leftover` missing; mint body has no `labels`.

- [ ] **Step 3: Minimal implementation**

`leftover.py`:

```python
def leftover_origin(labels: list[str] | None) -> str:
    labs = {str(x) for x in (labels or [])}
    hold = "act:hold" in labs
    ev = "origin:evaluate" in labs
    if hold and ev:
        return "both"
    if ev:
        return "evaluate"
    return "hold"


def is_leftover(case) -> bool:
    status = str(getattr(case, "status", "") or "").strip().lower()
    if status not in {"open", "investigating"}:
        return False
    if not str(getattr(case, "entity_id", "") or "").strip():
        return False
    labs = {str(x) for x in (getattr(case, "labels", None) or [])}
    return "act:hold" in labs or "origin:evaluate" in labs
```

Model columns on `Case`:

```python
claimed_by: Mapped[str | None] = mapped_column(String(256), nullable=True, default=None)
claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
last_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
last_act: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
```

`last_act` is the leftover-list SoR so the list never calls graph-service (spec: cheap / fail-soft). Values: `held` | `released` | `resolved`.

Alembic `20260831_010` revises `20260831_009`. Add the four nullable columns if missing. `init_db` `create_all` covers sqlite tests.

`CreateCaseRequest`: optional `labels: list[str] = []`, `last_outcome: str | None = None`.

`create_case`: `labels=list(body.labels or [])`, `last_outcome=(body.last_outcome or "").strip() or None`.

`maybe_create_case_for_outcome` body:

```python
"labels": ["origin:evaluate"],
"last_outcome": ctx.decision,
```

- [ ] **Step 4: Run tests to verify they pass**

Same commands as Step 2. Expected: PASS. Existing allow/flag enqueue tests still pass.

- [ ] **Step 5: Do not commit** unless the user asks.

---

### Task 2: Leftover list + claim + Hold/release/resolve

**Files:**
- Modify: `services/case-api/src/case_api/schemas.py` (`ObjectActRequest`)
- Modify: `services/case-api/src/case_api/leftover.py` (list row, claim)
- Modify: `services/case-api/src/case_api/main.py`
- Modify: `services/case-api/tests/test_leftovers.py`
- Modify: `services/case-api/tests/test_object_act.py`

**Interfaces:**
- Consumes: Task 1 columns + `is_leftover` + `DISPOSITION_REASON_CODES` + `escalate_status_for_reason` + `_persist_disposition_y_label`
- Produces:
  - `GET /v1/leftovers?tenant_id=&free_only=0` → `{ leftovers: [...], truncated: bool }` limit 100, `updated_at` desc
  - `POST /v1/leftovers/{case_id}/claim` → 200 same actor no-op; 409 `{detail: "claimed", claimed_by}`
  - Actor: `X-Actor-Id` header if non-blank, else `get_current_user(request).user_id` (same header as `cases.update`)
  - `ObjectActRequest.action` in `{hold, release, resolve}`; `reason_code: str | None`
  - Hold: mint/reuse leftover, `last_act=held`, claim if free, **409 if claimed by other** (does not steal)
  - Release: clear claim, `last_act=released`, case stays open, Person disposition `released`. Only claimer or a role that may update the case.
  - Resolve: required known `reason_code`, status via `escalate_status_for_reason("resolved", reason_code)`, `last_act=resolved`, `_persist_disposition_y_label` on leftover `trace_id`. 400 if missing/unknown.

- [ ] **Step 1: Write the failing HTTP tests** in `test_leftovers.py` using the existing `case_client` fixture pattern from `test_object_act.py`.

```python
def test_evaluate_mint_is_leftover_flag_and_blank_are_not(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    ev = case_client.post("/v1/cases", json={
        "tenant_id": "demo", "title": "Auto: deny payment e1",
        "entity_id": "e1", "trace_id": "tr-1",
        "labels": ["origin:evaluate"], "last_outcome": "deny",
    }, headers=_api_headers())
    assert ev.status_code == 201
    plain = case_client.post("/v1/cases", json={
        "tenant_id": "demo", "title": "manual",
        "entity_id": "e2", "trace_id": "tr-2",
    }, headers=_api_headers())
    assert plain.status_code == 201
    rows = case_client.get("/v1/leftovers", params={"tenant_id": "demo"}, headers=_api_headers()).json()
    ids = {r["entity_id"] for r in rows["leftovers"]}
    assert "e1" in ids
    assert "e2" not in ids
    e1 = next(r for r in rows["leftovers"] if r["entity_id"] == "e1")
    assert e1["origin"] == "evaluate"
    assert e1["last_outcome"] == "deny"


def test_claim_same_actor_noop_other_actor_409(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    hold = case_client.post("/v1/entities/buyer-a/act", json={"tenant_id": "demo", "action": "hold"}, headers=_api_headers())
    cid = hold.json()["case_id"]
    a = {**_api_headers(), "X-Actor-Id": "ana-a"}
    b = {**_api_headers(), "X-Actor-Id": "ana-b"}
    assert case_client.post(f"/v1/leftovers/{cid}/claim", params={"tenant_id": "demo"}, headers=a).status_code == 200
    again = case_client.post(f"/v1/leftovers/{cid}/claim", params={"tenant_id": "demo"}, headers=a)
    assert again.status_code == 200
    stolen = case_client.post(f"/v1/leftovers/{cid}/claim", params={"tenant_id": "demo"}, headers=b)
    assert stolen.status_code == 409
    assert stolen.json()["detail"] == "claimed" or stolen.json()["detail"]["claimed_by"] == "ana-a"


def test_hold_does_not_steal(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    case_client.post("/v1/entities/buyer-b/act", json={"tenant_id": "demo", "action": "hold"}, headers={**_api_headers(), "X-Actor-Id": "ana-a"})
    r = case_client.post("/v1/entities/buyer-b/act", json={"tenant_id": "demo", "action": "hold"}, headers={**_api_headers(), "X-Actor-Id": "ana-b"})
    assert r.status_code == 409


def test_resolve_requires_known_reason_and_closes(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    monkeypatch.setattr("case_api.main._persist_disposition_y_label", lambda *a, **k: None)
    case_client.post("/v1/entities/buyer-c/act", json={"tenant_id": "demo", "action": "hold"}, headers=_api_headers())
    bad = case_client.post("/v1/entities/buyer-c/act", json={"tenant_id": "demo", "action": "resolve"}, headers=_api_headers())
    assert bad.status_code == 400
    ok = case_client.post(
        "/v1/entities/buyer-c/act",
        json={"tenant_id": "demo", "action": "resolve", "reason_code": "FALSE_POSITIVE"},
        headers=_api_headers(),
    )
    assert ok.status_code == 200
    assert ok.json()["outcome"] == "resolved"
    listed = case_client.get("/v1/leftovers", params={"tenant_id": "demo"}, headers=_api_headers()).json()
    assert "buyer-c" not in {r["entity_id"] for r in listed["leftovers"]}


def test_release_clears_claim_stays_leftover(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    h = {**_api_headers(), "X-Actor-Id": "ana-a"}
    case_client.post("/v1/entities/buyer-d/act", json={"tenant_id": "demo", "action": "hold"}, headers=h)
    r = case_client.post("/v1/entities/buyer-d/act", json={"tenant_id": "demo", "action": "release"}, headers=h)
    assert r.status_code == 200
    rows = case_client.get("/v1/leftovers", params={"tenant_id": "demo", "free_only": 1}, headers=_api_headers()).json()
    d = next(x for x in rows["leftovers"] if x["entity_id"] == "buyer-d")
    assert d["claimed_by"] is None
    assert d["last_act"] == "released"
```

409 body: FastAPI `detail` may be a string or object. Implement as `HTTPException(409, detail={"detail": "claimed", "claimed_by": actor})` so JSON is `{"detail": {"detail": "claimed", "claimed_by": "ana-a"}}`. Tests should accept `body["detail"]["claimed_by"]` when detail is a dict. Spec JSON `{ "detail": "claimed", "claimed_by": "…" }` — use `JSONResponse(status_code=409, content={"detail": "claimed", "claimed_by": other})` to match the spec exactly.

- [ ] **Step 2: Run tests — expect FAIL** (404 leftovers, act rejects release/resolve).

```bash
cd services/case-api && PYTHONPATH=src:.:../shared pytest tests/test_leftovers.py tests/test_object_act.py -q
```

- [ ] **Step 3: Implement**

`ObjectActRequest._hold_only` → allow `hold|release|resolve`; add `reason_code: str | None = None`.

`_actor_id(request) -> str`: strip `X-Actor-Id` or `get_current_user(request).user_id`.

Claim helper: if `claimed_by` is None or equals actor → set both + `claimed_at=now(UTC)`, return case. Else raise 409 spec body.

List: filter `is_leftover`, optional `claimed_by IS NULL`, order `updated_at desc`, fetch 101, return 100 + `truncated`.

`last_act` on the row: case `last_act` if set; else `held` when `act:hold` and still leftover; else `null`.

SLA: `is_sla_breached(case.priority, case.created_at, sla_hours_override=case.sla_hours_override)`.

Auth on leftovers: `require_role_or_insecure_desk("analyst")` (same as Hold).

Hold: after mint/reuse, if claimed by other → 409 (do not steal). If free, claim. Set `last_act=held`.

Release: 403 if claimed by other and caller is not allowed to update the case (reuse whatever role gate `PATCH /v1/cases` uses; if none beyond analyst, only claimer). Clear claim. `last_act=released`. Disposition `released`.

Resolve: `normalize_reason_code`; 400 on ValueError. Status `escalate_status_for_reason("resolved", reason)`. `last_act=resolved`. y_label persist. Disposition `resolved`.

- [ ] **Step 4: Tests pass.** Existing hold tests still 200.

- [ ] **Step 5: Do not commit** unless asked.

---

### Task 3: Thin `/leftovers` desk

**Files:**
- Create: `frontend/src/pages/Leftovers.tsx`
- Create: `frontend/src/pages/Leftovers.test.tsx`
- Modify: `frontend/src/config/leanNav.ts`, `leanNav.test.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api/client.ts` (`listLeftovers`, `claimLeftover`, expand `actOnEntity`)
- Modify: `frontend/src/pages/Help.tsx` (leftover is `/leftovers`, not `/cases`)
- Modify: `frontend/src/pages/Help.test.tsx` if it asserts `/cases` leftover copy

**Interfaces:**
- Consumes: Task 2 APIs
- Produces: lean path `/leftovers`; visible iff graph plane on; row click claims if free then `/graph?entity_id=&tenant_id=`; claimed-by-other visible, not a work button

- [ ] **Step 1: Failing tests**

`leanNav.test.ts` — with graph URL set, `LEAN_NAV_PATHS.has("/leftovers")`, `isNavItemVisible("/leftovers")` true, `/cases` still false. Graph URL empty: `/leftovers` not visible.

`Leftovers.test.tsx`:

```tsx
it("claims a free row then opens Hunt", async () => {
  // mock listLeftovers + claimLeftover; click row; expect claim then navigate to /graph?entity_id=
});
it("does not claim a row owned by someone else", async () => {
  // claimed_by: "ana-b"; no claim call; no work button
});
```

- [ ] **Step 2: Run — expect FAIL** (`/leftovers` missing).

```bash
cd frontend && npm test -- --run src/config/leanNav.test.ts src/pages/Leftovers.test.tsx
```

- [ ] **Step 3: Thin page.** Table columns: entity, origin, last_outcome, last_act, claimed_by, sla. No KPIs, bulk, saved views, CaseDetail. Send `X-Actor-Id` from `tarka.desk_actor` || `analyst-web` on claim and act (same as PATCH).

`isNavItemVisible`: if `path === "/leftovers"` and graph plane off → false (even if in `LEAN_NAV_PATHS`). `isProductionSurfacePath("/leftovers")` true. `planeForPath("/leftovers")` is not graph — leftover without Hunt is a ticket queue; hide via the explicit graph-on gate, do not register leftover as a graph route.

`App.tsx`: `{ to: "/leftovers", label: "Leftovers", module: "cases" }` next to Hunt. Route `/leftovers` → page if graph on, else `PlaneOff plane="graph"` (or hide-only; PlaneOff is honest).

- [ ] **Step 4: Tests pass.**

- [ ] **Step 5: Do not commit** unless asked.

---

### Task 4: Hunt search_keys SQL

**Files:**
- Create: `services/graph-service/src/graph_service/search_keys.py`
- Create: `services/graph-service/tests/test_search_keys.py`
- Modify: `services/graph-service/src/graph_service/age_client.py` (`upsert_entity`, `search_entities`)
- Modify: `services/graph-service/src/graph_service/graph_runtime.py` (`upsert_entity` fail-soft key write)
- Modify: `services/graph-service/src/graph_service/main.py` (`q` strip, min length 2)
- Modify: `services/graph-service/tests/test_entity_search.py`

**Interfaces:**
- Consumes: `settings.database_url`, Person/Device upsert props
- Produces:
  - Table `search_keys`: `tenant_id`, `entity_external_id`, `key_kind` (`email|phone|external_id`), `key_norm`, `last_outcome`, `updated_at`. Unique `(tenant_id, key_kind, key_norm)`. Btree `(tenant_id, key_norm)`.
  - `normalize_search_key(raw) -> str` lower+strip
  - `outcome_rank(outcome) -> int` deny=0, review=1, flag=2, unknown/null=3, allow=4
  - `keys_from_upsert(entity_type, external_id, properties) -> list[tuple[kind, norm]]` — Person: external_id + email + phone; Device: external_id only
  - `search_prefix(tenant_id, q, limit=20) -> (hits, truncated)` — `key_norm LIKE lower(q)||'%'`, order rank then `entity_external_id`, dedupe entity, Person wins Device, limit 20, `truncated` if more
  - AGE `search_entities`: SQL only. Source must not contain `MATCH (n)` on that function after the table exists.
  - HTTP: empty or `len(q)<2` → `{entities:[], truncated: false}`, store not called
  - Failed key write: log, do not raise (same fail-soft as evaluate graph write)
  - No historical backfill

- [ ] **Step 1: Failing tests** in `test_search_keys.py`:

```python
from graph_service.search_keys import (
    keys_from_upsert,
    normalize_search_key,
    outcome_rank,
    sort_search_hits,
)


def test_normalize_and_person_keys():
    assert normalize_search_key("  Alice@Acme.com ") == "alice@acme.com"
    keys = keys_from_upsert("Person", "user-441", {"email": "Alice@Acme.com", "phone": "555-0100"})
    assert ("email", "alice@acme.com") in keys
    assert ("external_id", "user-441") in keys
    assert keys_from_upsert("Device", "dev-1", {"email": "x@y.com"}) == [("external_id", "dev-1")]


def test_outcome_rank_unknown_between_flag_and_allow():
    assert outcome_rank("deny") < outcome_rank("review") < outcome_rank("flag")
    assert outcome_rank(None) > outcome_rank("flag")
    assert outcome_rank(None) < outcome_rank("allow")
    assert outcome_rank("") == outcome_rank(None)


def test_sort_dedupe_person_wins_device():
    hits = [
        {"entity_external_id": "user-441", "key_kind": "external_id", "labels": ["Device"], "last_outcome": "allow"},
        {"entity_external_id": "user-441", "key_kind": "email", "labels": ["Person"], "last_outcome": "deny"},
        {"entity_external_id": "other", "key_kind": "email", "labels": ["Person"], "last_outcome": None},
    ]
    rows = sort_search_hits(hits, limit=20)
    assert [r["entity_id"] for r in rows] == ["user-441", "other"]
    assert rows[0]["last_outcome"] == "deny"
```

`test_entity_search.py`:

```python
def test_search_http_q_shorter_than_2_no_store(monkeypatch):
    # same as empty q — store not called; body {"entities": [], "truncated": False}

def test_age_search_source_has_no_match_n_when_sql_path():
    import inspect
    from graph_service import age_client
    src = inspect.getsource(age_client.search_entities)
    assert "MATCH (n)" not in src
```

The AST test is the production bar for AGE. If `search_entities` delegates to `search_keys.search_prefix`, the MATCH must leave `search_entities`. Keep the old MATCH function only as `_search_entities_scan_fallback` for Neo4j/Janus empty-table fallback — **not** called from AGE `search_entities`.

Neo4j/Janus: if `search_prefix` returns rows, use them. If the table is empty / missing, keep existing backend search and set `truncated=True` when that fallback scans. Production AGE never calls the fallback.

- [ ] **Step 2: Run — expect FAIL.**

```bash
cd services/graph-service && PYTHONPATH=src:.:../shared GRAPH_BACKEND=neo4j pytest tests/test_search_keys.py tests/test_entity_search.py -q
```

- [ ] **Step 3: Implement.** Graph-service has no alembic — `CREATE TABLE IF NOT EXISTS` + indexes on first write/search (same pattern as `decision_context_store`). Use AGE `database_url` / asyncpg. `upsert_entity` in `graph_runtime` after successful store upsert: `try: await upsert_search_keys(...) except: log`.

HTTP `entities_search`: after strip/[:256], if `len(needle) < 2` return empty + `truncated: false` without calling store.

Search hit shape stays `{entity_id, tenant_id, labels, last_outcome, matched_on, ...}` so the typeahead can show outcome.

- [ ] **Step 4: Tests pass.** Existing empty-q test still passes; update it to assert `truncated: false` if the handler now always sends that key.

- [ ] **Step 5: Do not commit** unless asked.

---

### Task 5: Hunt desk honesty (unknown, 8 of N, lag)

**Files:**
- Modify: `frontend/src/domain/graphInvestigation.ts`
- Modify: `frontend/src/domain/graphInvestigation.test.ts`
- Modify: `frontend/src/components/GraphContextPanel.tsx` + `.test.tsx`
- Modify: `frontend/src/pages/GraphInvestigationPage.tsx`
- Modify: `frontend/src/api/client.ts` (`GraphSearchHit.last_outcome?`)

**Interfaces:**
- Consumes: stored `properties.last_outcome`, `graph.latestEvaluate`, `entityHistory.trace_ids` / `last_trace_id`, `HUNT_HIERARCHY_EXPAND_CAP`
- Produces:
  - `lastOutcomeLabel(node|hit) -> "deny"|"review"|"flag"|"allow"|"unknown"`
  - `hierarchyInstrumentFanout(...) -> { ids: string[], total: number }` — count before cap; ids still capped at 8
  - `graphLaggedEvaluate(latest, history) -> bool` — true when latest.trace_id is non-blank and not in history.trace_ids and ≠ last_trace_id
  - Header + typeahead show label; unknown is a word, not allow color
  - Pane: **Showing 8 of N instruments** when `total > 8`
  - Lag copy: `Graph lagged this evaluate. Receipt is source of truth.` 404/null latest → no banner. Do not block Hold.

- [ ] **Step 1: Failing domain tests**

```ts
it("labels missing last_outcome as unknown, not allow", () => {
  expect(lastOutcomeLabel(n("p", { properties: {} }))).toBe("unknown");
  expect(lastOutcomeLabel(n("p", { properties: { last_outcome: "deny" } }))).toBe("deny");
});

it("counts instruments before the cap", () => {
  const nodes = [n("buyer", { labels: ["Person"] }), ...Array.from({ length: 10 }, (_, i) => n(`dev-${i}`, { labels: ["Device"] }))];
  const edges = Array.from({ length: 10 }, (_, i) => ({ from_id: "buyer", to_id: `dev-${i}`, type: "USES_DEVICE" }));
  const r = hierarchyInstrumentFanout("buyer", nodes, edges);
  expect(r.total).toBe(10);
  expect(r.ids).toHaveLength(8);
});

it("lags when latest trace is not on the object", () => {
  expect(graphLaggedEvaluate({ trace_id: "tr-new" }, { last_trace_id: "tr-old", trace_ids: ["tr-old"] })).toBe(true);
  expect(graphLaggedEvaluate({ trace_id: "tr-old" }, { last_trace_id: "tr-old", trace_ids: ["tr-old"] })).toBe(false);
  expect(graphLaggedEvaluate(null, { last_trace_id: "tr-old", trace_ids: [] })).toBe(false);
});
```

Keep `decisionToastText` for the canvas toast (existing test). Add unknown as a distinct canvas class in `paintStoredRisk` / node className — not the allow color. Prefer a `data-outcome` / class helper `outcomePaintClass(label)` so unknown ≠ allow.

Panel test: mock `graph.latestEvaluate` resolving `{ trace_id: "tr-new" }` and history `{ last_trace_id: "tr-old", trace_ids: ["tr-old"] }` → banner text present. `latestEvaluate` null → no banner. First-paint `hunt-eval-buyer` / pack-why regression stays green.

- [ ] **Step 2: Run — expect FAIL.**

```bash
cd frontend && npm test -- --run src/domain/graphInvestigation.test.ts src/components/GraphContextPanel.test.tsx
```

- [ ] **Step 3: Implement.** `hierarchyInstrumentIds` can stay as a wrapper that returns `.ids` so existing callers do not churn; page/panel use fanout for the caption. Typeahead row shows `lastOutcomeLabel(hit)`.

Resolve/release buttons on the Person pane (Hunt stays the work surface). Resolve posts `reason_code` from existing `DISPOSITION_REASON_CODES`. Do not navigate to `/cases/:id`.

- [ ] **Step 4: Tests pass.** Including existing GraphContextPanel first-paint evaluate.

- [ ] **Step 5: Do not commit** unless asked.

---

### Task 6: Score gate (do not claim 4.0 / 3.8 without this)

Walk the spec checklists. If a row is missing, that dimension is not 3.8 / 4.0. Do not start no-code / desk polish until both pass.

**Leftover 3.8 must-be-true**

1. Evaluate deny/review mint with flag on creates `origin:evaluate` leftover. List is `/leftovers`, not `/cases`.
2. Hold creates/reuses leftover. List shows hold and evaluate origins.
3. Second actor: claim 409. Hold does not steal.
4. Resolve on Hunt with `FALSE_POSITIVE` or `CONFIRMED_FRAUD`. Still on `/graph`. Case terminal (not in leftover list).

**Hunt 4.0 must-be-true**

1. Typeahead hits Person by **email** (`search_keys`), not only `entity_id`.
2. One Person with `last_outcome`, one without — unknown labeled, not allow color.
3. >8 instruments → **Showing 8 of N**.
4. Lag banner when latest evaluate `trace_id` ≠ object history. Receipt still loadable. Hold not blocked.
5. `hunt-eval-buyer` first-paint pack-why still green.
6. AGE `search_entities` source has no `MATCH (n)`. Empty/`q`<2 does not scan.

If any row fails, the score is not met. Desk polish / no-code stays closed.

---

## Self-review

| Spec requirement | Task |
|------------------|------|
| Leftover predicate + evaluate `origin:evaluate` + `last_outcome` | 1 |
| Claim 200/409, Hold no-steal, release, resolve + y_label | 2 |
| `/leftovers` lean, `/cases` hidden, row → Hunt | 3 |
| `search_keys` SQL, AGE no MATCH, unknown rank | 4 |
| Header/canvas/typeahead unknown, 8 of N, lag | 5 |
| Demo witnesses / production bar | 6 |
| No fat cases, no-code, FinCEN, consortium | Global out |

No placeholders. Types: `claimed_by` / `last_outcome` / `last_act` / `leftover_origin` / `lastOutcomeLabel` / `hierarchyInstrumentFanout` / `graphLaggedEvaluate` are consistent across tasks.
