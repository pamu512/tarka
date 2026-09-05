# Field registry + onboarding map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tenant field registry (name + explanation + source) plus buyer-key maps; author catalog is registry ⋈ manifest ⋈ hops/growth; evaluate remaps before Redis; packs cannot author unmapped names.

**Architecture:** Pure helpers in `services/shared/field_registry.py` (seed load, name rules, remap, discover, catalog join inputs). Overlay + maps in decision-api Postgres (`field_registry`, `field_maps`). `build_author_catalog` filters redis/payload by registry names; hops/growth stay `#377`. One remap call in `run_evaluate_decision` after replay signature, before amount/Redis. Demo PUTs 403 when `TARKA_DESK_PROFILE=demo`. Do not change fraud-desk compose.

**Tech Stack:** Python 3 (decision-api, shared), SQLAlchemy + Alembic, FastAPI, React + vitest, pytest.

**Spec:** [docs/superpowers/specs/2026-09-05-field-registry-map-design.md](../specs/2026-09-05-field-registry-map-design.md)

**Branch:** `honesty/field-registry-v1` from `#377` / `feat/desk-demo-vs-product`. Worktree: `/Users/pamu/Documents/GitHub/tarka-wt/desk-demo-vs-product` (or a new worktree from that branch). Workspace `master` does not have `author_catalog`.

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- Empty plane URL = that plane off. Graph keys **absent** when the graph URL is empty (do not write `0`).
- No `rate` / `baseline_ratio`. No new Rust `velocity_v1`. No `velocity()` in pack JSON.
- No windows, baselines, or hop etypes **in the registry**.
- New registry names: `^[a-z][a-z0-9_]{0,127}$` and must **not** start with `tx_`.
- Legacy aliases stay read-only on the allow-list. Do not insert them as registry rows.
- Do not reuse `feature_definitions`. Do not add `desk_provision.json`.
- Do not open the `EventType` enum. Do not change SDK missing≠false.
- Do not attach `registry_id` on evaluate features.
- No named third-party desks in published copy. Do not call Tarka OSS in new docs. Keep `scripts/oss/` path names.
- Do not change `make demo`, fraud-desk compose, `SentencePackPanel`, or clone-demo.
- API roles are `admin`/`analyst`/`viewer`/`service`. Registry **writes** use `require_role("analyst")` like `/v1/rules`. Desk panel is `DESK_PROFILE === "product"` + `RequireRole` `RiskArchitect`.
- Do not commit unless the user asked. Skip **Step: Commit** otherwise.

---

## File map

| File | Responsibility |
|------|----------------|
| `services/decision-api/src/decision_api/data/field_registry_v1.json` | Seed rows (`tarka_core`) |
| `services/shared/field_registry.py` | Load seed, name rules, remap, discover, merge list |
| `services/shared/author_catalog.py` | Join: redis/payload filtered by registry names |
| `services/decision-api/src/decision_api/models.py` | `FieldRegistryRow`, `FieldMap` |
| `services/decision-api/alembic/versions/20260905_010_field_registry.py` | Tables |
| `services/decision-api/src/decision_api/field_store.py` | Async overlay + maps |
| `services/decision-api/src/decision_api/field_api.py` | `/v1/fields*` |
| `services/decision-api/src/decision_api/rule_api.py` | Catalog `tenant_id`; pack field reject |
| `services/decision-api/src/decision_api/evaluate/pipeline.py` | Remap after replay |
| `services/decision-api/src/decision_api/config.py` | `tarka_desk_profile` |
| `services/decision-api/src/decision_api/main.py` | Include field router |
| `services/shadow_agent/pack_author_contract.py` | `allowed_fields` arg |
| `services/shadow_agent/PACK_AUTHOR.md` | One map-workflow paragraph |
| `frontend/src/api/client.ts` | `fields.*`; catalog `tenant_id` |
| `frontend/src/components/FieldMapPanel.tsx` | Product map UI |
| `frontend/src/pages/Rules.tsx` | Mount panel |
| `docs/docs/guides/field-registry-onboarding.md` | Operator guide |

---

### Task 1: Seed + name rules + remap + discover

**Files:**
- Create: `services/decision-api/src/decision_api/data/field_registry_v1.json`
- Create: `services/shared/field_registry.py`
- Create: `services/decision-api/tests/test_field_registry.py`

**Interfaces:**
- Consumes: `counter_manifest_v1.json` `feature_outputs`, `author_catalog.PAYLOAD_FIELDS`, `author_catalog.IDENTITY_FIELDS`
- Produces:

```python
REGISTRY_NAME_RE: re.Pattern[str]  # r"^[a-z][a-z0-9_]{0,127}$"
SOURCES: frozenset[str]  # tarka_core | sdk_tarka | mapped_buyer | enrichment | new_feature

def validate_registry_name(name: str) -> str:
    """Strip. Raise ValueError if empty, not REGISTRY_NAME_RE, or startswith tx_."""

def load_seed_rows() -> list[dict]:
    """Read field_registry_v1.json. Missing/invalid file → [] (log once). Each row: name, explanation, source=tarka_core."""

def seed_names() -> frozenset[str]:
    return frozenset(r["name"] for r in load_seed_rows() if r.get("name"))

def merge_registry_rows(*, seed: list[dict], overlay: list[dict]) -> list[dict]:
    """By name: overlay wins. Do not invent names."""

def apply_field_maps(payload: dict, maps: list[tuple[str, str]]) -> dict:
    """Copy payload. For (buyer_key, registry_name): if buyer_key in out and registry_name not in out, set it. Do not delete buyer_key. Do not write 0."""

def discover_payload(payload: dict, *, registry_names: set[str], maps: dict[str, str]) -> dict:
    """already_named / mapped / candidates as spec JSON."""
```

- [ ] **Step 1: Write the failing tests**

Create `services/decision-api/tests/test_field_registry.py`:

```python
from author_catalog import IDENTITY_FIELDS, PAYLOAD_FIELDS
from field_registry import (
    apply_field_maps,
    discover_payload,
    load_seed_rows,
    merge_registry_rows,
    seed_names,
    validate_registry_name,
)
from fraud_aggregates import _bundled_manifest_feature_outputs, valid_feature_output_rows


def test_seed_has_core_names_not_growth_or_hops():
    names = seed_names()
    assert "event_count_7d" in names
    assert "avg_amount_1h" in names
    assert "amount" in names
    assert "relation_growth_1h" not in names
    assert "USES_DEVICE" not in names


def test_seed_covers_manifest_payload_identity():
    manifest = {r["name"] for r in valid_feature_output_rows(_bundled_manifest_feature_outputs())}
    assert manifest <= seed_names()
    assert set(PAYLOAD_FIELDS) <= seed_names()
    assert set(IDENTITY_FIELDS) <= seed_names()


def test_validate_rejects_tx_prefix_and_bad_shape():
    for bad in ("tx_count_1h", "EventCount", "1h_count", ""):
        try:
            validate_registry_name(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_apply_maps_fills_amount_without_clobber_or_zero():
    out = apply_field_maps({"txn_amt": 9}, [("txn_amt", "amount")])
    assert out["amount"] == 9
    assert out["txn_amt"] == 9
    both = apply_field_maps({"amount": 4, "txn_amt": 9}, [("txn_amt", "amount")])
    assert both["amount"] == 4
    missing = apply_field_maps({"other": 1}, [("txn_amt", "amount")])
    assert "amount" not in missing


def test_discover_splits_named_mapped_candidates():
    d = discover_payload(
        {"amount": 1, "txn_amt": 1, "order_channel": "web"},
        registry_names={"amount"},
        maps={"txn_amt": "amount"},
    )
    assert d["already_named"] == ["amount"]
    assert d["mapped"] == [{"buyer_key": "txn_amt", "registry_name": "amount"}]
    assert d["candidates"] == [{"buyer_key": "order_channel", "suggested_source": "new_feature"}]


def test_merge_overlay_wins_same_name():
    merged = merge_registry_rows(
        seed=[{"name": "amount", "explanation": "seed", "source": "tarka_core"}],
        overlay=[{"name": "order_channel", "explanation": "who sold", "source": "new_feature"}],
    )
    names = {r["name"] for r in merged}
    assert names == {"amount", "order_channel"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pamu/Documents/GitHub/tarka-wt/desk-demo-vs-product && PYTHONPATH=services/shared:services/decision-api/src python -m pytest services/decision-api/tests/test_field_registry.py -q`

Expected: FAIL (import error)

- [ ] **Step 3: Seed JSON + helpers**

`field_registry_v1.json` is a JSON array. Every `feature_outputs[].name`, every `PAYLOAD_FIELDS` entry, and every `IDENTITY_FIELDS` entry not already listed. `source` is always `tarka_core`. `explanation` is one short line (kind + window for redis; identity/payload restated). No growth names. No hop etypes.

`field_registry.py` implements the interfaces above. `load_seed_rows` looks next to this module is wrong — the file lives in decision-api data. Resolve path:

```python
def _seed_path() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        cand = p / "services/decision-api/src/decision_api/data/field_registry_v1.json"
        if cand.is_file():
            return cand
        cand = p / "decision_api/data/field_registry_v1.json"
        if cand.is_file():
            return cand
    return here.parent / "decision_api/data/field_registry_v1.json"
```

Shared tests run with `PYTHONPATH=services/shared:services/decision-api/src` so the second candidate hits.

- [ ] **Step 4: Run tests to verify they pass**

Run: same pytest command. Expected: PASS

- [ ] **Step 5: Commit** (skip unless the user asked)

```bash
git add services/decision-api/src/decision_api/data/field_registry_v1.json \
  services/shared/field_registry.py services/decision-api/tests/test_field_registry.py
git commit -m "$(cat <<'EOF'
feat: seed field registry names and remap helpers

EOF
)"
```

---

### Task 2: Catalog join

**Files:**
- Modify: `services/shared/author_catalog.py`
- Modify: `services/decision-api/tests/test_author_catalog.py`

**Interfaces:**
- Consumes: `field_registry.seed_names`
- Produces:

```python
def build_author_catalog(
    *,
    graph_url: str,
    growth_windows: list[dict] | None,
    registry_names: frozenset[str] | None = None,
    overlay_names: frozenset[str] | None = None,
) -> dict:
    """registry_names None → seed_names(). Empty frozenset → redis=[] and payload=[].
    redis = manifest rows whose name ∈ registry_names.
    payload = (PAYLOAD_FIELDS ∩ registry_names) ∪ (overlay_names − redis names).
    growth/hops unchanged from #377.
    """
```

- [ ] **Step 1: Write the failing tests**

Append to `test_author_catalog.py`:

```python
def test_catalog_seed_only_payload_omits_entity_id():
    cat = build_author_catalog(graph_url="", growth_windows=None)
    payload = {p["name"] for p in cat["payload"]}
    assert "amount" in payload
    assert "entity_id" not in payload


def test_catalog_overlay_name_appears_in_payload():
    seed = __import__("field_registry", fromlist=["seed_names"]).seed_names()
    cat = build_author_catalog(
        graph_url="",
        growth_windows=None,
        registry_names=seed | frozenset({"order_channel"}),
        overlay_names=frozenset({"order_channel"}),
    )
    assert "order_channel" in {p["name"] for p in cat["payload"]}
    redis = {r["name"] for r in cat["redis"]}
    assert "event_count_7d" in redis


def test_catalog_restricted_registry_drops_redis_keeps_hops():
    cat = build_author_catalog(
        graph_url="http://g",
        growth_windows=[{"window": "1h", "threshold": 5}],
        registry_names=frozenset({"amount"}),
        overlay_names=frozenset(),
    )
    assert {r["name"] for r in cat["redis"]} == set()
    assert {p["name"] for p in cat["payload"]} == {"amount"}
    assert {g["name"] for g in cat["growth"]} == {"relation_growth_1h"}
    assert {h["etype"] for h in cat["hops"]} == {
        "USES_DEVICE",
        "HAS_EMAIL",
        "HAS_PHONE",
        "HAS_CARD",
        "HAS_LIST",
    }
```

Existing `#377` tests must keep passing (`registry_names=None` = seed).

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=services/shared:services/decision-api/src python -m pytest services/decision-api/tests/test_author_catalog.py::test_catalog_overlay_name_appears_in_payload -q`

Expected: FAIL (unexpected keyword)

- [ ] **Step 3: Implement join**

In `build_author_catalog`:

```python
from field_registry import seed_names as _seed_names

names = seed_names() if registry_names is None else frozenset(registry_names)
overlay = frozenset(overlay_names or ())
redis = [_redis_entry(r) for r in _redis_rows() if r["name"] in names]
redis_name_set = {r["name"] for r in redis}
payload_core = [n for n in PAYLOAD_FIELDS if n in names]
payload_extra = [n for n in sorted(overlay) if n not in redis_name_set and n not in payload_core]
payload = [{"name": n} for n in payload_core + payload_extra]
```

Growth/hops blocks unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=services/shared:services/decision-api/src python -m pytest services/decision-api/tests/test_author_catalog.py services/shadow_agent/tests/test_pack_author_contract.py -q`

Expected: PASS (`ALLOWED_FIELDS` still seed ∪ identity ∪ aliases)

- [ ] **Step 5: Commit** (skip unless asked)

---

### Task 3: Models, Alembic, store

**Files:**
- Modify: `services/decision-api/src/decision_api/models.py`
- Create: `services/decision-api/alembic/versions/20260905_010_field_registry.py`
- Create: `services/decision-api/src/decision_api/field_store.py`
- Create: `services/decision-api/tests/test_field_store.py`

**Interfaces:**
- Consumes: `AsyncSession`, Task 1 validators
- Produces:

```python
class FieldRegistryRow(Base):  # __tablename__ = "field_registry"
    # uq_field_registry_tenant_name (tenant_id, name)
    # tenant_id, name, explanation, source, created_at, updated_at

class FieldMap(Base):  # __tablename__ = "field_maps"
    # uq_field_maps_tenant_buyer (tenant_id, buyer_key)
    # tenant_id, buyer_key, registry_name, created_at, updated_at

async def list_overlay(session, tenant_id: str) -> list[FieldRegistryRow]: ...
async def get_overlay(session, tenant_id: str, name: str) -> FieldRegistryRow | None: ...
async def upsert_overlay(session, tenant_id: str, name: str, explanation: str, source: str) -> FieldRegistryRow:
    """validate_registry_name. source in SOURCES. explanation strip 1..500.
    If name in seed_names(): raise FieldRegistrySeedLocked.
    """

async def list_maps(session, tenant_id: str) -> list[FieldMap]: ...
async def upsert_map(session, tenant_id: str, buyer_key: str, registry_name: str) -> FieldMap:
    """buyer_key stripped non-empty max 256, preserve spelling.
    registry_name must be in seed_names() or overlay for tenant. Else FieldRegistryUnknownName.
    """
```

- [ ] **Step 1: Write the failing store test**

```python
# test_field_store.py — sqlite+aiosqlite, Base.metadata.create_all
# upsert_overlay("order_channel") then list_overlay includes it
# upsert_overlay("event_count_1h") raises FieldRegistrySeedLocked
# upsert_overlay("tx_count_1h") raises ValueError
# upsert_map("txn_amt", "amount") works
# upsert_map("x", "not_a_field") raises FieldRegistryUnknownName
```

- [ ] **Step 2: Run to verify fail**

Run: `PYTHONPATH=services/shared:services/decision-api/src python -m pytest services/decision-api/tests/test_field_store.py -q`

Expected: FAIL

- [ ] **Step 3: Models + Alembic + store**

Alembic `revision = "20260905_010"`, `down_revision = "20260510_009"`. Postgres `String` columns (not native ENUM) so SQLite tests match. Import `FieldRegistryRow` / `FieldMap` from `models` in `field_store` so `create_all` sees them when tests import store.

`upsert_overlay` / `upsert_map` `session.add` + `await session.flush()`.

- [ ] **Step 4: Run to verify pass**

Expected: PASS

- [ ] **Step 5: Commit** (skip unless asked)

---

### Task 4: HTTP API

**Files:**
- Create: `services/decision-api/src/decision_api/field_api.py`
- Modify: `services/decision-api/src/decision_api/config.py` — add `tarka_desk_profile: str = ""` (env `TARKA_DESK_PROFILE`)
- Modify: `services/decision-api/src/decision_api/main.py` — `app.include_router(field_router)` next to `rule_router`
- Create: `services/decision-api/tests/test_field_api.py`

**Interfaces:**
- Router prefix `/v1/fields`, tags `fields`
- GET list/get: `require_role("analyst")` (same as rules reads; insecure-desk tests that skip auth still work if they construct a bare FastAPI like author-catalog — **do not** add auth middleware on the unit app; match `test_author_catalog`)
- PUT: if `settings.tarka_desk_profile.strip().lower() == "demo"` → 403 `{"detail": "maps persist on product Postgres"}`
- Register `/maps` and `/discover` **before** `/{name}`

```python
@router.get("")
@router.get("/maps")
@router.put("/maps")
@router.post("/discover")
@router.get("/{name}")
@router.put("/{name}")
```

GET `""` and GET `"/maps"` require `tenant_id` query (400 if missing).

PUT `/{name}` body: `{ "explanation": str, "source": str }`. Seed name → 400. Bad source / empty explanation → 422.

PUT `/maps` body: `{ "tenant_id", "buyer_key", "registry_name" }`.

POST `/discover` body: `{ "tenant_id", "payload" }`. Non-dict payload → 422.

List GET 503 only when the session execute raises (product Postgres down). Do not invent names.

- [ ] **Step 1: Write HTTP tests** (bare FastAPI + `create_all` + `get_session` override)

```python
async def test_maps_route_not_captured_as_name(client):
    r = await client.get("/v1/fields/maps", params={"tenant_id": "t1"})
    assert r.status_code == 200
    assert r.json() == []

async def test_put_tx_name_400(client):
    r = await client.put("/v1/fields/tx_count_1h", json={"explanation": "no", "source": "new_feature"})
    assert r.status_code == 400

async def test_put_and_discover(client):
    r = await client.put(
        "/v1/fields/order_channel",
        json={"explanation": "who sold", "source": "new_feature"},
        params={"tenant_id": "t1"},
    )
    # PUT /{name} also accepts tenant_id query
    assert r.status_code == 200
    await client.put(
        "/v1/fields/maps",
        json={"tenant_id": "t1", "buyer_key": "txn_amt", "registry_name": "amount"},
    )
    d = await client.post(
        "/v1/fields/discover",
        json={"tenant_id": "t1", "payload": {"txn_amt": 1, "order_channel": "web", "amount": 2}},
    )
    body = d.json()
    assert "amount" in body["already_named"]
    assert any(x["buyer_key"] == "txn_amt" for x in body["mapped"])
    assert any(x["buyer_key"] == "order_channel" for x in body["candidates"]) or (
        "order_channel" in body["already_named"]
    )

async def test_demo_put_403(client, monkeypatch):
    monkeypatch.setattr(field_api.settings, "tarka_desk_profile", "demo")
    r = await client.put(
        "/v1/fields/maps",
        json={"tenant_id": "t1", "buyer_key": "a", "registry_name": "amount"},
    )
    assert r.status_code == 403
```

After overlay `order_channel`, that name is already_named on discover (key equals registry name). `candidates` is empty for that key. The spec example assumed `order_channel` was not yet a row. Test: discover **before** PUT row → `order_channel` is a candidate; after PUT row, it is `already_named`. Split the test that way.

- [ ] **Step 2: Run to verify fail**

Expected: FAIL (no router)

- [ ] **Step 3: Implement `field_api.py` + include + settings**

PUT `/{name}` needs `tenant_id` query (same as list). 404 on GET unknown name.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=services/shared:services/decision-api/src python -m pytest services/decision-api/tests/test_field_api.py -q`

Expected: PASS

- [ ] **Step 5: Commit** (skip unless asked)

---

### Task 5: Evaluate remap

**Files:**
- Modify: `services/decision-api/src/decision_api/evaluate/pipeline.py`
- Modify: `services/decision-api/src/decision_api/field_store.py` — add `async def load_maps_or_empty(session, tenant_id) -> list[tuple[str, str]]` (except → `[]` + log)
- Create: `services/decision-api/tests/test_evaluate_field_remap.py`

**Interfaces:**
- After replay signature block (~line 209), before HMAC / feature merge:

```python
from field_registry import apply_field_maps
from decision_api.field_store import load_maps_or_empty

_maps = await load_maps_or_empty(session, body.tenant_id)
if _maps:
    body.payload = apply_field_maps(
        dict(body.payload) if isinstance(body.payload, dict) else {},
        _maps,
    )
```

Do not remap before replay (replay hashes the buyer payload).

- [ ] **Step 1: Write tests that do not boot the full pipeline**

Full `run_evaluate_decision` is too heavy. Test the hook as a function in `field_store` + assert pipeline source contains the call, **and** a unit that simulates the call site:

```python
def test_pipeline_source_remaps_after_replay():
    text = Path("services/decision-api/src/decision_api/evaluate/pipeline.py").read_text()
    assert "apply_field_maps" in text
    assert text.index("check_and_store_replay_signature") < text.index("apply_field_maps")


@pytest.mark.asyncio
async def test_load_maps_or_empty_swallows_and_apply(session):
    # upsert map txn_amt→amount, then
    maps = await load_maps_or_empty(session, "t1")
    out = apply_field_maps({"txn_amt": 9}, maps)
    assert out["amount"] == 9
```

- [ ] **Step 2: Run to verify fail**

Expected: FAIL (`apply_field_maps` not in pipeline)

- [ ] **Step 3: Insert the call site exactly after the replay block**

- [ ] **Step 4: Run to verify pass**

Also run: `PYTHONPATH=services/shared:services/decision-api/src python -m pytest services/decision-api/tests/test_golden_counters.py services/decision-api/tests/test_counter_manifest.py -q`

Expected: PASS (no maps → no-op)

- [ ] **Step 5: Commit** (skip unless asked)

---

### Task 6: Pack author reject + live catalog tenant

**Files:**
- Modify: `services/decision-api/src/decision_api/rule_api.py`
- Modify: `services/shared/field_registry.py` or a tiny helper in `rule_api`:

```python
def when_field_errors(pack: dict, allowed: frozenset[str]) -> list[str]:
    errors: list[str] = []
    for rule in pack.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        rid = rule.get("id", "unknown")
        for cond in rule.get("when") or []:
            if not isinstance(cond, dict):
                continue
            field = cond.get("field") or ""
            if field and field not in allowed:
                errors.append(
                    f"rule {rid}: unknown field '{field}'; map it or add a registry row"
                )
    return errors
```

- Modify: `services/shadow_agent/pack_author_contract.py` — `validate_ai_authored_pack(doc, allowed_fields: frozenset[str] | None = None)` uses `allowed_fields or ALLOWED_FIELDS`
- Modify: `services/shadow_agent/PACK_AUTHOR.md` — after the allowed-field list, add:

```
Unknown `when.field` values are rejected. Map the buyer key or add a registry
row (`source: new_feature`) before authoring. Legacy `tx_*` aliases remain
valid; do not create new `tx_*` registry names. Tenant overlay names exist
on the decision-api write path; a cold shadow_agent import only sees the seed
allow-list (`ponytail:` no registry HTTP client in shadow_agent this slice).
```

- Modify: `services/decision-api/tests/test_author_catalog.py` — catalog GET `?tenant_id=` includes overlay name after store upsert (or monkeypatch overlay names)
- Create: `services/decision-api/tests/test_rule_field_reject.py`

**Interfaces:**
- `_live_author_catalog(tenant_id: str | None = None)`: if tenant set, load overlay names (fail → seed-only + log); pass `registry_names=seed|overlay`, `overlay_names=overlay` into `build_author_catalog`
- `GET /v1/rules/author-catalog?tenant_id=`
- `create_rule_pack` / `update_rule_pack` / `_validate_ai_authored_pack`: after structural validate, `when_field_errors(pack, ai_allowed_fields(_live_author_catalog(tenant)))`. Human POST has no tenant on the pack — use seed-only catalog (`tenant_id=None`) **plus** `IDENTITY` **plus** `LEGACY_ALIASES`. That still rejects `not_a_field` and allows `tx_count_1h`. Overlay-only names on human POST require `tenant_id` query on create/update (optional). If omitted, seed+aliases only.

```python
# create_rule_pack / update_rule_pack
tenant_id: str | None = Query(default=None)
...
ferr = when_field_errors(pack, ai_allowed_fields(_live_author_catalog(tenant_id)))
if ferr:
    raise HTTPException(422, detail={"validation_errors": ferr})
```

Do **not** change `validate_rule_pack` (stdlib CI). Do **not** reject on evaluate of existing files.

- [ ] **Step 1: Write failing tests**

```python
async def test_create_pack_rejects_unknown_field(rules_client):
    r = await rules_client.post(
        "/v1/rules",
        json={"name": "ghost", "rules": [{"id": "r1", "when": [{"field": "not_a_field", "op": "eq", "value": 1}], "score_delta": 5}]},
    )
    assert r.status_code == 422
    assert "map it or add a registry row" in str(r.json())


async def test_create_pack_allows_legacy_alias(rules_client):
    r = await rules_client.post(
        "/v1/rules",
        json={"name": "legacy_tx", "rules": [{"id": "r1", "when": [{"field": "tx_count_1h", "op": "gte", "value": 3}], "score_delta": 5}]},
    )
    assert r.status_code in (201, 409, 422)
    # 422 only if governance/other; field itself must not be the reason
    if r.status_code == 422:
        assert "tx_count_1h" not in str(r.json()).lower() or "unknown field" not in str(r.json())
```

Governance secret may 403/401 on full app. Bare FastAPI like `test_author_catalog` has no governance — `_require_rule_governance` may no-op when secret unset. If create fails for filename collision, use a unique name.

Also: `validate_ai_authored_pack({"...", "when":[{"field":"order_channel"}]}, allowed_fields=frozenset({"order_channel", ...}))` ok; without the extra set, `order_channel` fails.

- [ ] **Step 2: Run to verify fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run**

`PYTHONPATH=services/shared:services/decision-api/src:services/shadow_agent python -m pytest services/decision-api/tests/test_rule_field_reject.py services/decision-api/tests/test_author_catalog.py services/shadow_agent/tests/test_pack_author_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit** (skip unless asked)

---

### Task 7: Desk panel (product)

**Files:**
- Modify: `frontend/src/api/client.ts` — `rules.authorCatalog(tenantId?: string)`; add `fields` client
- Modify: `frontend/src/domain/authorCatalogSession.ts` — pass tenant
- Create: `frontend/src/components/FieldMapPanel.tsx`
- Create: `frontend/src/components/FieldMapPanel.test.tsx`
- Modify: `frontend/src/pages/Rules.tsx` — mount after the field-catalog toggle block
- Modify: `frontend/src/pages/Rules.test.tsx` — mock `fields` if imported via client

**Interfaces:**

```ts
export const fields = {
  list(tenantId: string) {
    return request<FieldRow[]>(`/api/decisions/v1/fields?tenant_id=${encodeURIComponent(tenantId)}`);
  },
  upsert(tenantId: string, name: string, body: { explanation: string; source: string }) {
    return request(`/api/decisions/v1/fields/${encodeURIComponent(name)}?tenant_id=${encodeURIComponent(tenantId)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },
  maps(tenantId: string) {
    return request<FieldMapRow[]>(`/api/decisions/v1/fields/maps?tenant_id=${encodeURIComponent(tenantId)}`);
  },
  putMap(body: { tenant_id: string; buyer_key: string; registry_name: string }) {
    return request(`/api/decisions/v1/fields/maps`, { method: "PUT", body: JSON.stringify(body) });
  },
  discover(body: { tenant_id: string; payload: Record<string, unknown> }) {
    return request<DiscoverOut>(`/api/decisions/v1/fields/discover`, { method: "POST", body: JSON.stringify(body) });
  },
};

authorCatalog(tenantId?: string) {
  const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
  return request<AuthorCatalog>(`/api/decisions/v1/rules/author-catalog${q}`);
}
```

`FieldMapPanel` (`data-testid="field-map-panel"`):

- Render `null` unless `DESK_PROFILE === "product"`
- Wrap writes in existing `RequireRole` `RiskArchitect` (list still behind the same gate — one panel)
- Tenant = `searchParams tenant_id` or workspace tenant or `"demo"`
- Load `fields.list` + `fields.maps`
- Textarea JSON → Discover → show candidates
- Candidate action: upsert `new_feature` with explanation from a one-line input, then `putMap` if they typed a buyer_key→existing name instead

Keep it one screen. No new route. No `/cases`.

- [ ] **Step 1: Write FieldMapPanel tests**

```tsx
vi.mock("@/config/leanNav", () => ({ DESK_PROFILE: "product" }));
// mock fields.list / discover
it("shows panel on product", async () => {
  render(<FieldMapPanel tenantId="t1" />);
  expect(await screen.findByTestId("field-map-panel")).toBeTruthy();
});
```

Second file or same with `vi.doMock` is painful — split:

```tsx
// FieldMapPanel.test.tsx default product mock
it("lists seed name amount", ...);
it("discover shows candidate", ...);
```

```tsx
// FieldMapPanel.demo.test.tsx
vi.mock("@/config/leanNav", () => ({ DESK_PROFILE: "demo" }));
it("renders nothing on demo", () => {
  const { container } = render(<FieldMapPanel tenantId="t1" />);
  expect(container.querySelector("[data-testid=field-map-panel]")).toBeNull();
});
```

- [ ] **Step 2: Run to verify fail**

Run: `cd frontend && npx vitest run src/components/FieldMapPanel.test.tsx src/components/FieldMapPanel.demo.test.tsx`

Expected: FAIL

- [ ] **Step 3: Implement panel + wire Rules + catalog tenant**

`Rules.tsx`: `loadAuthorCatalog(sandboxTenantDefault)` in the existing effect (add tenant to deps). Render `<FieldMapPanel tenantId={sandboxTenantDefault} />` under the field-catalog grid.

- [ ] **Step 4: Run frontend tests**

`npx vitest run src/components/FieldMapPanel.test.tsx src/components/FieldMapPanel.demo.test.tsx src/pages/Rules.test.tsx src/domain/authorCatalog.test.ts`

Expected: PASS

- [ ] **Step 5: Commit** (skip unless asked)

---

### Task 8: Docs

**Files:**
- Create: `docs/docs/guides/field-registry-onboarding.md`
- Modify: `docs/docs/guides/ingest-replay-onboarding.md` — one sentence + link at the top (do not rewrite)
- PACK_AUTHOR paragraph is Task 6

**Doc must include:** seed vs overlay; map then author; discover → row → map; demo limitation (seed file, PUT 403 when `TARKA_DESK_PROFILE=demo`; compose unchanged this slice); empty seed → catalog redis/payload empty, hops/growth unchanged; `tx_*` migrate-only; windows stay on `counter_manifest_v1.json`; growth on graph policy GET; no `desk_provision`; Elastic-2.0 / do not say OSS.

- [ ] **Step 1: Write the guide** (no TBD)

- [ ] **Step 2: Check the new guide against repo lint rules**

The tree lint rejects editor-vendor names and named competitor desks. The new guide must not contain them. Do not label Tarka as open source. `scripts/oss/` as a path is already in the repo; do not add that label in new prose.

Run the same lint job the PR will run (`make lint` or the workflow `lint` step). Expected: PASS on the new guide.

- [ ] **Step 3: Commit** (skip unless asked)

---

## Self-review

1. **Spec coverage:** seed, overlay, maps, discover, catalog join, evaluate remap, pack reject, demo PUT 403, product panel, docs, no windows/hops in registry, legacy aliases, `#377` catalog tests kept.
2. **Placeholders:** none.
3. **Types:** `apply_field_maps(payload, list[tuple[str,str]])`, `build_author_catalog(..., registry_names, overlay_names)`, store exceptions `FieldRegistrySeedLocked` / `FieldRegistryUnknownName`.

## Execution note

Copy `docs/superpowers/specs/2026-09-05-field-registry-map-design.md` and this plan into the `#377` worktree if they are only on workspace `master`. Implement on `honesty/field-registry-v1` branched from `feat/desk-demo-vs-product`.
