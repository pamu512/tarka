# Marketplace P0 — Packs, Pre-payout Holds, Collusion Rail

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship full-feature marketplace/q-comm/logistics/food vertical packs, durable evaluate-driven payout holds, and an API-backed multi-party collusion rail on CaseDetail.

**Architecture:** Extend `vertical_packs.py` with four packs (reuse install/promote/kill). Persist payout holds in integration-ingress Postgres; decision-api calls an internal hold API after evaluate when `checkpoint=payout` and action tags fire. Case-api exposes `GET .../multi-party-links` (graph risk_propagation + role map + cases by entity_id); CaseDetail consumes only that API.

**Tech Stack:** Python/FastAPI, SQLAlchemy + Alembic (integration-ingress), existing evaluate pipeline, React/TS CaseDetail, pytest.

**Spec:** [`docs/superpowers/specs/2026-08-07-marketplace-p0-packs-payout-collusion-design.md`](../specs/2026-08-07-marketplace-p0-packs-payout-collusion-design.md)

## Global Constraints

- No stubs, placeholders, or demo-only source of truth for new surfaces (full features).
- Do **not** re-home `loyalty-abuse` multi-gate into Tarka; reuse typology vocabulary only; optional later HTTP adapter.
- Location = partner enrichment; collusion = graph + rules.
- Reuse payout-delay REST paths/UI; replace `demo_aggregate` as sole data source.
- Ratings/grades stay private (`RATING_PRIVACY`).
- Do not forge LIVE partner pins.

## File map

| File | Role |
| --- | --- |
| `services/decision-api/src/decision_api/vertical_packs.py` | Four packs ≥5 rules each |
| `services/decision-api/tests/test_marketplace_vertical_packs.py` | List/install/kill tests |
| `docs/docs/guides/vertical-packs-marketplace-delivery.md` | Operator guide |
| `services/integration-ingress/.../models.py` + alembic | `marketplace_payout_holds` table |
| `services/integration-ingress/.../payout_hold_store.py` | Durable CRUD |
| `services/integration-ingress/.../payout_delay_automation.py` | List = durable + mule automation writes |
| `services/integration-ingress/.../main.py` | Internal create-hold route |
| `services/decision-api/.../payout_hold_bridge.py` | Post-evaluate HTTP to ingress |
| `services/decision-api/.../evaluate/pipeline.py` or `main.py` evaluate exit | Call bridge |
| `services/case-api/.../main.py` | `entity_id` filter on list; multi-party-links |
| `services/case-api/.../multi_party_links.py` | Role map + assemble response |
| `frontend/.../MultiPartyLinksRail.tsx` | CaseDetail UI |
| `frontend/src/api/client.ts` | Client method |

---

### Task 1: Vertical packs + kill-gate tests

**Files:**
- Modify: `services/decision-api/src/decision_api/vertical_packs.py`
- Create: `services/decision-api/tests/test_marketplace_vertical_packs.py`
- Create: `docs/docs/guides/vertical-packs-marketplace-delivery.md`

**Interfaces:**
- Consumes: existing `get_vertical_pack`, `list_vertical_packs`, `_DEFAULT_KILL`, install/promote in `rule_api.py`
- Produces: pack ids `marketplace`, `qcommerce`, `logistics`, `food_delivery` each with ≥5 rules and tags from spec

- [ ] **Step 1: Write failing list test**

```python
# services/decision-api/tests/test_marketplace_vertical_packs.py
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api.vertical_packs import get_vertical_pack, list_vertical_packs

REQUIRED = ("marketplace", "qcommerce", "logistics", "food_delivery")
ACTION_TAGS = {"action:payout_hold", "action:payout_delay"}
RISK_TAGS = {
    "risk:collusion_shared_device",
    "risk:promo_farm",
    "risk:courier_spoof",
    "risk:refund_burst",
    "risk:multi_account_partner",
}

def test_marketplace_verticals_listed_with_rule_floor():
    catalog = list_vertical_packs()
    for name in REQUIRED:
        assert name in catalog
        pack = get_vertical_pack(name)
        assert pack is not None
        assert len(pack["rules"]) >= 5
        assert pack.get("kill_criteria")
        tags = {t for r in pack["rules"] for t in r.get("tags") or []}
        assert f"vertical:{name}" in tags or any(str(t).startswith("vertical:") for t in tags)
        assert tags & ACTION_TAGS or tags & RISK_TAGS
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd services/decision-api && python -m pytest tests/test_marketplace_vertical_packs.py::test_marketplace_verticals_listed_with_rule_floor -v`  
Expected: FAIL (`assert 'marketplace' in catalog` or similar)

- [ ] **Step 3: Implement four packs**

In `_PACKS` of `vertical_packs.py`, add four entries matching fintech shape. Each rule needs `id`, `when`, `tags`, `score_delta`, `description`. Include at least these themes (fields must already evaluate — use `amount`, `account_age_days`, `transaction_count_24h`, `is_bot`, `is_emulator`, and tag-style fields only if evaluate already exposes them as features; prefer feature fields used by ecommerce/fintech packs):

**marketplace (≥5):** collusion shared-device velocity; refund burst; review inflation proxy (`review_to_delivery_ratio` if present else high refund rate field); young seller high payout; `action:payout_hold` on high amount + risk tags.  
**qcommerce (≥5):** promo farm velocity; multi-account (`accounts_on_device_24h` or `transaction_count_24h` + bot); referral burst; rider spoof tag/`is_emulator`; `action:payout_delay`.  
**logistics (≥5):** multi-account partner; order accept velocity; emulator; payout hold; shared device.  
**food_delivery (≥5):** refund/cancel burst; courier spoof/emulator; diner–merchant velocity; promo farm; payout hold.

Example rule skeleton (repeat pattern; do not leave packs under 5 rules):

```python
"marketplace": {
    "name": "Vertical Marketplace",
    "version": 1,
    "velocity_presets": "standard",
    "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
    "rules": [
        {
            "id": "mkt_shared_device_collusion",
            "when": [
                {"field": "transaction_count_24h", "op": "gte", "value": 15},
                {"field": "account_age_days", "op": "lte", "value": 21},
            ],
            "tags": ["vertical:marketplace", "risk:collusion_shared_device"],
            "score_delta": 24,
            "description": "Young account high velocity — collusion / multi-account pattern",
        },
        # ... ≥4 more including at least one action:payout_hold
    ],
    "tag_rules": [],
},
```

Steal tag names from loyalty-abuse typologies (`risk:promo_farm`, etc.) and seller_integrity thresholds for descriptions — do not import loyalty-abuse package.

- [ ] **Step 4: Add HTTP install kill test**

Mirror `test_kill_criteria_promote_gate.py` client fixture; POST `/v1/rules/vertical-packs/marketplace/install` with bad metrics → 409; good metrics → 201. Parametrize one other pack name.

- [ ] **Step 5: Run tests — expect PASS**

Run: `cd services/decision-api && python -m pytest tests/test_marketplace_vertical_packs.py tests/test_kill_criteria_promote_gate.py -q`  
Expected: PASS

- [ ] **Step 6: Write guide**

Create `docs/docs/guides/vertical-packs-marketplace-delivery.md`: install/promote curl, tag contract (`action:payout_*`, risk tags), pre-payout checkpoint (`metadata.checkpoint=payout`), note loyalty-abuse owns LTV gates, link CLAIM_LOCK/RATING_PRIVACY briefly as private.

- [ ] **Step 7: Commit**

```bash
git add services/decision-api/src/decision_api/vertical_packs.py \
  services/decision-api/tests/test_marketplace_vertical_packs.py \
  docs/docs/guides/vertical-packs-marketplace-delivery.md
git commit -m "$(cat <<'EOF'
feat: add marketplace q-comm logistics food vertical packs

EOF
)"
```

---

### Task 2: Durable payout hold model + Alembic

**Files:**
- Modify: `services/integration-ingress/src/integration_ingress/models.py`
- Create: `services/integration-ingress/alembic/versions/20260807_007_marketplace_payout_holds.py`
- Create: `services/integration-ingress/src/integration_ingress/payout_hold_store.py`
- Create: `services/integration-ingress/tests/test_payout_hold_store.py`

**Interfaces:**
- Consumes: `Base` from `integration_ingress.db`, session patterns from other models
- Produces:
  - model `MarketplacePayoutHold`
  - `async def upsert_hold(session, **, ...) -> dict`
  - `async def list_holds(session, tenant_id, limit) -> list[dict]`
  - `async def release_hold(session, tenant_id, payout_id, *, released_by) -> dict | None`

- [ ] **Step 1: Failing store test**

```python
import pytest
from integration_ingress.payout_hold_store import upsert_hold, list_holds, release_hold

@pytest.mark.asyncio
async def test_upsert_list_release_roundtrip(session):  # use project’s async session fixture or create engine
    row = await upsert_hold(
        session,
        tenant_id="t1",
        payout_id="po_1",
        entity_id="seller_1",
        status="held",
        hold_reason="tag:action:payout_hold",
        held_by="evaluate",
        decision_id="dec_1",
        trace_id="tr_1",
        tags=["action:payout_hold", "vertical:marketplace"],
        amount=120.5,
        currency="USD",
        hold_duration_hours=72,
    )
    assert row["status"] == "held"
    listed = await list_holds(session, "t1", limit=10)
    assert any(p["payout_id"] == "po_1" for p in listed)
    released = await release_hold(session, "t1", "po_1", released_by="analyst")
    assert released["status"] == "released"
```

Wire `session` fixture like other ingress async DB tests (follow `test_marketplace_webhook_logs` / db fixture patterns in that package).

- [ ] **Step 2: Run — expect FAIL** (module missing)

- [ ] **Step 3: Add model + migration**

`MarketplacePayoutHold` columns per spec: tenant_id, payout_id, entity_id, status, hold_reason, held_by, decision_id, trace_id, tags (JSON), amount, currency, mule_score (nullable), held_at, scheduled_release_at, released_at. Unique `(tenant_id, payout_id)`.

Alembic: `revision = "20260807_007"`, `down_revision = "20260518_006"` (verify head with `cd services/integration-ingress && alembic heads`).

- [ ] **Step 4: Implement `payout_hold_store.py`** upsert/list/release (real SQLAlchemy, no process-global as sole store)

- [ ] **Step 5: Tests PASS**

Run: `cd services/integration-ingress && python -m pytest tests/test_payout_hold_store.py -q`

- [ ] **Step 6: Commit**

```bash
git add services/integration-ingress/src/integration_ingress/models.py \
  services/integration-ingress/src/integration_ingress/payout_hold_store.py \
  services/integration-ingress/alembic/versions/20260807_007_marketplace_payout_holds.py \
  services/integration-ingress/tests/test_payout_hold_store.py
git commit -m "$(cat <<'EOF'
feat: durable marketplace payout hold store

EOF
)"
```

---

### Task 3: Wire payout-delay API to durable store + mule writes

**Files:**
- Modify: `services/integration-ingress/src/integration_ingress/payout_delay_automation.py`
- Modify: `services/integration-ingress/src/integration_ingress/main.py` (list/config/release + internal create)
- Modify: `services/integration-ingress/tests/test_payout_delay_automation.py`
- Create: `services/integration-ingress/tests/test_payout_delay_durable.py`

**Interfaces:**
- Consumes: `payout_hold_store.*`
- Produces:
  - `POST /v1/internal/marketplace/payout-holds` (service auth: reuse existing internal/API-key pattern on ingress, or `X-Internal-Token` matching env `INGRESS_INTERNAL_TOKEN`)
  - `GET /v1/marketplace/payout-delay` returns `"source": "durable"` and rows from DB
  - Release endpoint updates durable row
  - Mule threshold path **writes** durable holds when listing/scanning entities that have mule_score ≥ threshold (if current demo mule path remains, convert it to upsert held rows for entities that still use graph mule_score input — do not invent fake payouts as the only list content)

- [ ] **Step 1: Failing API test**

```python
@pytest.mark.asyncio
async def test_list_returns_durable_hold_not_demo_only(client, session):
    await upsert_hold(session, tenant_id="demo", payout_id="po_real", entity_id="e1",
                      status="held", hold_reason="tag:action:payout_hold", held_by="evaluate",
                      decision_id="d", trace_id="t", tags=["action:payout_hold"], amount=10, currency="USD",
                      hold_duration_hours=24)
    await session.commit()
    r = await client.get("/v1/marketplace/payout-delay", params={"tenant_id": "demo"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] in ("durable", "durable+automation")
    assert any(p["payout_id"] == "po_real" for p in body["payouts"])
```

- [ ] **Step 2: Run — FAIL** (`source` still `demo_aggregate`)

- [ ] **Step 3: Refactor `build_payout_delay_payload`**

- Load config as today  
- `payouts = await list_holds(...)` (make function async if needed; update `main.py` callers)  
- Apply mule automation only by creating/updating durable holds when an explicit mule_score input path exists; remove RNG `_payout_row` from the happy-path list  
- Set `source` to `durable`  
- Keep response keys `config`, `summary`, `events`, `payouts` so UI does not break  

- [ ] **Step 4: Internal create endpoint**

```python
@app.post("/v1/internal/marketplace/payout-holds", status_code=201)
async def internal_create_payout_hold(body: PayoutHoldCreateBody, session=Depends(get_session), ...):
    # auth: require internal token
    row = await upsert_hold(session, ...)
    await session.commit()
    # optional: deliver_marketplace_block_webhook / record with signal "payout_hold"
    return row
```

- [ ] **Step 5: Release uses `release_hold`**

- [ ] **Step 6: Tests PASS** including updated unit tests that no longer assume demo RNG ids

- [ ] **Step 7: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: serve payout-delay from durable holds

EOF
)"
```

---

### Task 4: Evaluate → payout hold bridge (decision-api)

**Files:**
- Create: `services/decision-api/src/decision_api/payout_hold_bridge.py`
- Modify: evaluate exit in `services/decision-api/src/decision_api/evaluate/pipeline.py` **or** `run_evaluate_decision` in `main.py` (whichever returns final tags — prefer single call site after tags finalized)
- Create: `services/decision-api/tests/test_payout_hold_from_evaluate.py`
- Modify: `docs/docs/guides/vertical-packs-marketplace-delivery.md` (checkpoint curl)
- Config: `INTEGRATION_INGRESS_URL`, `INGRESS_INTERNAL_TOKEN` in decision-api settings

**Interfaces:**
- Consumes: final evaluate `tags`, `metadata.checkpoint` / `event_type`, `metadata.payout_id`, entity_id, tenant_id, decision/trace ids
- Produces: `async def maybe_create_payout_hold(*, http, settings, ...) -> None` — fire-and-forget with timeout; failures logged, evaluate still succeeds

- [ ] **Step 1: Failing unit test for bridge trigger**

```python
import pytest
from decision_api.payout_hold_bridge import should_create_payout_hold, build_hold_payload

def test_should_create_on_payout_checkpoint_and_action_tag():
    assert should_create_payout_hold(
        metadata={"checkpoint": "payout", "payout_id": "po_9"},
        tags=["vertical:marketplace", "action:payout_hold"],
    )
    assert not should_create_payout_hold(metadata={"checkpoint": "order"}, tags=["action:payout_hold"])
    assert not should_create_payout_hold(metadata={"checkpoint": "payout"}, tags=["risk:promo_farm"])

def test_build_hold_payload_maps_fields():
    p = build_hold_payload(
        tenant_id="t", entity_id="e", tags=["action:payout_delay"],
        metadata={"checkpoint": "payout", "payout_id": "po_1", "amount": 50},
        decision_id="d", trace_id="tr",
    )
    assert p["payout_id"] == "po_1"
    assert p["status"] == "held"
    assert "action:payout_delay" in p["tags"]
```

- [ ] **Step 2: FAIL then implement helpers**

- [ ] **Step 3: Async POST with httpx**

```python
async def maybe_create_payout_hold(*, http, base_url: str, token: str, payload: dict) -> None:
    if not base_url or not token:
        return
    try:
        r = await http.post(
            f"{base_url.rstrip('/')}/v1/internal/marketplace/payout-holds",
            json=payload,
            headers={"X-Internal-Token": token},
            timeout=2.0,
        )
        r.raise_for_status()
    except Exception:
        log.exception("payout_hold_bridge_failed")
```

- [ ] **Step 4: Hook after evaluate** when `should_create_payout_hold` — use `BackgroundTasks` if available so latency stays low

- [ ] **Step 5: Integration-style test** with `httpx.MockTransport` or respx proving POST called

- [ ] **Step 6: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: create payout holds from evaluate action tags

EOF
)"
```

---

### Task 5: Case list by entity_id + multi-party-links API

**Files:**
- Create: `services/case-api/src/case_api/multi_party_links.py`
- Modify: `services/case-api/src/case_api/main.py` (`list_cases` + new route)
- Create: `services/case-api/tests/test_multi_party_links.py`

**Interfaces:**
- Consumes: graph service `risk_propagation` (same as `GET /v1/cases/{id}/graph`)
- Produces:
  - `list_cases(..., entity_id: str | None = None)`
  - `GET /v1/cases/{case_id}/multi-party-links?depth=3`
  - `map_labels_to_roles(labels: list[str]) -> list[str]`
  - `async def build_multi_party_links(session, case, *, http, depth) -> dict`

Role map (deterministic):

```python
_ROLE_MAP = {
    "buyer": ("buyer", "consumer", "diner", "customer", "user"),
    "seller": ("seller", "merchant", "shop", "restaurant"),
    "courier": ("courier", "driver", "partner", "rider", "dasher"),
}

def map_labels_to_roles(labels: list[str]) -> list[str]:
    roles: list[str] = []
    lower = {str(x).lower() for x in labels}
    for role, keys in _ROLE_MAP.items():
        if lower & set(keys):
            roles.append(role)
    return roles or ["unknown"]
```

- [ ] **Step 1: Unit test role mapper + API test with mocked graph**

```python
def test_map_labels_courier_and_seller():
    from case_api.multi_party_links import map_labels_to_roles
    assert "courier" in map_labels_to_roles(["Driver", "Device"])
    assert map_labels_to_roles(["Widget"]) == ["unknown"]

@pytest.mark.asyncio
async def test_multi_party_links_joins_cases(client, session, monkeypatch):
    # create anchor case + neighbor case same tenant
    # monkeypatch httpx get risk_propagation to return neighbor entity with labels ["Courier"]
    r = await client.get(f"/v1/cases/{anchor_id}/multi-party-links", params={"tenant_id": "t"})
    assert r.status_code == 200
    body = r.json()
    assert body["links"]
    assert body["links"][0]["roles"] == ["courier"]
    assert any(c["case_id"] for c in body["links"][0]["cases"])
```

Check whether case routes need `tenant_id` query — match `/v1/cases/{id}/graph` auth pattern.

- [ ] **Step 2: FAIL then implement**

`build_multi_party_links`:
1. Load case or 404  
2. Call graph risk_propagation  
3. For each entity: roles, distance, score, path_description, shared_signals from rel_types if present  
4. Query `Case` where tenant_id + entity_id in neighbor ids (use new filter)  
5. Attach cases list (id, status, optional disposition from labels if stored)  
6. Sort distance asc, risk desc  
7. On graph failure: return `{"links": [], "degraded": true, "degraded_reason": "graph_unavailable"}` with 200 **or** 502 — pick **200 + degraded** to match fail-soft desk UX; document in OpenAPI/docstring

- [ ] **Step 3: `list_cases` add `entity_id: str | None = None`** → `q = q.where(Case.entity_id == entity_id)` when set

- [ ] **Step 4: Tests PASS**

Run: `cd services/case-api && python -m pytest tests/test_multi_party_links.py -q`

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: multi-party links API for case collusion rail

EOF
)"
```

---

### Task 6: CaseDetail Multi-party links UI

**Files:**
- Create: `frontend/src/components/CaseView/MultiPartyLinksRail.tsx`
- Create: `frontend/src/components/CaseView/MultiPartyLinksRail.test.tsx` (or project’s vitest path)
- Modify: `frontend/src/api/client.ts` (or `cases.ts`) — `cases.multiPartyLinks(caseId, params)`
- Modify: `frontend/src/pages/CaseDetail.tsx` — mount desktop + mobile beside knowledge graph

**Interfaces:**
- Consumes: `GET /api/cases/v1/cases/{id}/multi-party-links` (via existing proxy prefix used by CaseDetail)
- Produces: rail showing role chips, entity id, path, linked case links, loading/error/empty/degraded

- [ ] **Step 1: Failing component test** — render fixture JSON with courier + linked case; assert role text and case link href

- [ ] **Step 2: Implement fetch hook + rail** (mirror `KnowledgeGraphSidebar` patterns: loading spinner, retry, `data-testid="multi-party-links-rail"`)

- [ ] **Step 3: Wire CaseDetail** — pass `caseId`, `tenantId`; do not invent roles client-side

- [ ] **Step 4: Run frontend tests**

Run: `cd frontend && npm test -- --run MultiPartyLinks` (adjust to repo’s test runner)

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: CaseDetail multi-party collusion links rail

EOF
)"
```

---

### Task 7: Program verification + guide polish

**Files:**
- Modify: `docs/docs/guides/vertical-packs-marketplace-delivery.md` — end-to-end story
- Modify: `docs/superpowers/specs/2026-08-07-marketplace-p0-packs-payout-collusion-design.md` — status → Implemented (date)

- [ ] **Step 1: Run full verification suite**

```bash
cd services/decision-api && python -m pytest tests/test_marketplace_vertical_packs.py tests/test_payout_hold_from_evaluate.py -q
cd ../integration-ingress && python -m pytest tests/test_payout_hold_store.py tests/test_payout_delay_durable.py -q
cd ../case-api && python -m pytest tests/test_multi_party_links.py -q
cd ../../frontend && npm test -- --run MultiPartyLinks
```

Expected: all PASS

- [ ] **Step 2: Manual smoke checklist (document results in PR)**

1. Install `marketplace` pack with healthy metrics  
2. Evaluate with `metadata.checkpoint=payout` and features that fire `action:payout_hold`  
3. `GET /v1/marketplace/payout-delay?tenant_id=...` shows hold, `source=durable`  
4. Open CaseDetail with fixture multi-party data — rail shows roles + cases  

- [ ] **Step 3: Commit docs**

```bash
git commit -m "$(cat <<'EOF'
docs: marketplace P0 verify guide and mark spec implemented

EOF
)"
```

---

## Spec coverage check

| Spec requirement | Task |
| --- | --- |
| Four packs ≥5 rules + kill gates | Task 1 |
| Guide tag + pre-payout contract | Task 1, 4, 7 |
| Durable hold model + Alembic | Task 2 |
| List/release/webhooks; no demo-as-sole-source | Task 3 |
| Evaluate bridge on checkpoint+tags | Task 4 |
| multi-party-links API + roles + cases | Task 5 |
| CaseDetail rail API-only | Task 6 |
| Full verification | Task 7 |
| Appendix A: no loyalty-abuse re-home | Global + Task 1 notes |
| friendly_fraud / seller heuristics as vocabulary only | Task 1 descriptions/tags |

## Placeholder scan

None intentional. If mule_score live graph join is unavailable in ingress, Task 3 must still serve durable evaluate-created holds as primary path (mule path can upsert when score is supplied on create body).
