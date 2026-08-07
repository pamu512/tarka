# Marketplace P1 — Payout Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Marketplace P0 payout gaps: hold≠delay, webhooks, no SHA mule seed, hardened S2S auth, honest release 404, bridge failure metric.

**Architecture:** decision-api maps tags→`status`/`hold_duration_hours` and POSTs internal create; ingress persists durable rows, fires marketplace webhooks on material create/release, syncs mule holds only from explicit `mule_candidates`, and returns 404 on missing release.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, httpx, pytest, existing `marketplace_webhook_logs`.

**Spec:** [`docs/superpowers/specs/2026-08-07-marketplace-p1-payout-hardening-design.md`](../specs/2026-08-07-marketplace-p1-payout-hardening-design.md)

## Global Constraints

- No stubs; durable `marketplace_payout_holds` remains source of truth.
- Do not re-home loyalty-abuse; do not forge LIVE partner pins.
- Ratings/grades stay private (`RATING_PRIVACY`).
- Webhook failures must not roll back hold/release; bridge failures must not fail evaluate.
- Never invent `payout_id`s via SHA/hash on the list path.

## File map

| File | Role |
| --- | --- |
| `services/decision-api/src/decision_api/payout_hold_bridge.py` | status/duration/event_type; metrics on fail |
| `services/decision-api/src/decision_api/decision_outcome.py` | pass `event_type` into bridge task |
| `services/decision-api/tests/test_payout_hold_from_evaluate.py` | delay/pending, event_type, metric |
| `services/integration-ingress/src/integration_ingress/payout_hold_store.py` | `scheduled_release_at` for `pending`; upsert change flag |
| `services/integration-ingress/src/integration_ingress/payout_delay_automation.py` | config defaults; remove SHA; candidate sync; release None |
| `services/integration-ingress/src/integration_ingress/marketplace_webhook_logs.py` | signal literals `payout_hold` / `payout_release` |
| `services/integration-ingress/src/integration_ingress/main.py` | auth compare_digest; webhooks; release 404; config PATCH fields |
| `services/integration-ingress/tests/test_payout_delay_durable.py` | auth neg, mule no-seed, webhook, 404 |
| `services/integration-ingress/tests/test_payout_delay_automation.py` | update for candidates / default automation off |
| `docs/docs/guides/vertical-packs-marketplace-delivery.md` | operator docs |

---

### Task 1: Bridge — hold vs delay + event_type checkpoint

**Files:**
- Modify: `services/decision-api/src/decision_api/payout_hold_bridge.py`
- Modify: `services/decision-api/src/decision_api/decision_outcome.py`
- Modify: `services/decision-api/tests/test_payout_hold_from_evaluate.py`

**Interfaces:**
- Produces:
  - `should_create_payout_hold(*, metadata, tags, event_type: str | None = None) -> bool`
  - `resolve_hold_status_and_hours(tags) -> tuple[str, int]` → `("held", 72)` or `("pending", 24)`; hold wins if both tags
  - `build_hold_payload(...)` includes `status` + `hold_duration_hours`
  - `maybe_create_payout_hold_from_evaluate(..., event_type: str = "", metrics_inc=None)`

- [ ] **Step 1: Failing tests**

```python
def test_should_create_on_event_type_payout():
    assert should_create_payout_hold(
        metadata={"payout_id": "po_1"},
        tags=["action:payout_hold"],
        event_type="payout",
    )
    assert not should_create_payout_hold(
        metadata={"checkpoint": "order"},
        tags=["action:payout_hold"],
        event_type="purchase",
    )

def test_resolve_delay_pending_and_hold_wins():
    from decision_api.payout_hold_bridge import resolve_hold_status_and_hours
    assert resolve_hold_status_and_hours(["action:payout_delay"]) == ("pending", 24)
    assert resolve_hold_status_and_hours(["action:payout_hold", "action:payout_delay"]) == ("held", 72)

def test_build_hold_payload_pending_for_delay():
    p = build_hold_payload(
        tenant_id="t", entity_id="e", tags=["action:payout_delay"],
        metadata={"checkpoint": "payout", "payout_id": "po_1"},
        decision_id="d", trace_id="tr",
    )
    assert p["status"] == "pending"
    assert p["hold_duration_hours"] == 24
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd services/decision-api && python -m pytest tests/test_payout_hold_from_evaluate.py::test_should_create_on_event_type_payout tests/test_payout_hold_from_evaluate.py::test_resolve_delay_pending_and_hold_wins tests/test_payout_hold_from_evaluate.py::test_build_hold_payload_pending_for_delay -q`  
Expected: FAIL (missing `resolve_hold_status_and_hours` / event_type)

- [ ] **Step 3: Implement**

In `payout_hold_bridge.py`:

```python
DEFAULT_HOLD_HOURS = 72
DEFAULT_DELAY_HOURS = 24

def should_create_payout_hold(*, metadata, tags, event_type: str | None = None) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    checkpoint = str(meta.get("checkpoint") or "").strip().lower()
    et = str(event_type or "").strip().lower()
    if checkpoint not in PAYOUT_CHECKPOINTS and et not in PAYOUT_CHECKPOINTS:
        return False
    return bool(set(tags or []) & ACTION_TAGS)

def resolve_hold_status_and_hours(tags: list[str] | None) -> tuple[str, int]:
    tag_set = set(tags or [])
    if "action:payout_hold" in tag_set:
        return "held", DEFAULT_HOLD_HOURS
    if "action:payout_delay" in tag_set:
        return "pending", DEFAULT_DELAY_HOURS
    return "held", DEFAULT_HOLD_HOURS
```

`build_hold_payload`: set `status, hours = resolve_hold_status_and_hours(tags)` into payload.

`maybe_create_payout_hold_from_evaluate`: accept `event_type`, pass into `should_create`; keep failures logged (metric in Task 5).

`decision_outcome.py`: pass `event_type=ctx.event_type` into `maybe_create_payout_hold_from_evaluate` kwargs; gate still uses `should_create_payout_hold(..., event_type=ctx.event_type)`.

- [ ] **Step 4: Tests PASS**

Run: `cd services/decision-api && python -m pytest tests/test_payout_hold_from_evaluate.py -q`  
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: map payout delay tags to pending holds and event_type checkpoint

EOF
)"
```

---

### Task 2: Store pending schedule + upsert materialization flag

**Files:**
- Modify: `services/integration-ingress/src/integration_ingress/payout_hold_store.py`
- Modify: `services/integration-ingress/tests/test_payout_hold_store.py`

**Interfaces:**
- Produces: `upsert_hold(...) -> dict` with `"_materialized": True` when insert or status transition into `held`/`pending`; False on no-op-ish refresh (same status held/pending already). Prefer top-level key stripped before HTTP response, or return `tuple[dict, bool]` — **use return `tuple[dict[str, Any], bool]`** `(row_dict, materialized)`.

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_upsert_pending_sets_schedule_and_materialized_flag(session):
    row, mat = await upsert_hold(
        session, tenant_id="t1", payout_id="po_p", entity_id="e1",
        status="pending", hold_reason="tag:action:payout_delay", held_by="evaluate",
        hold_duration_hours=24,
    )
    assert mat is True
    assert row["status"] == "pending"
    assert row["scheduled_release_at"] is not None
    row2, mat2 = await upsert_hold(
        session, tenant_id="t1", payout_id="po_p", entity_id="e1",
        status="pending", hold_reason="tag:action:payout_delay", held_by="evaluate",
        hold_duration_hours=24,
    )
    assert mat2 is False
```

Update existing roundtrip test to unpack `(row, _)` if signature changes.

- [ ] **Step 2: FAIL then implement**

For `pending` and `held`: set `scheduled_release_at = now + timedelta(hours=hours)`.  
`materialized = row was None or previous status not in {held, pending} or previous status != new status` (insert or transition into held/pending counts True; identical pending→pending refresh False).

- [ ] **Step 3: PASS + commit**

```bash
git commit -m "$(cat <<'EOF'
feat: schedule pending payout holds and report upsert materialization

EOF
)"
```

---

### Task 3: Kill SHA mule seed; explicit mule_candidates; default automation off

**Files:**
- Modify: `services/integration-ingress/src/integration_ingress/payout_delay_automation.py`
- Modify: `services/integration-ingress/src/integration_ingress/main.py` (config PATCH body)
- Modify: `services/integration-ingress/tests/test_payout_delay_durable.py`
- Modify: `services/integration-ingress/tests/test_payout_delay_automation.py`

**Interfaces:**
- Produces:
  - `get_payout_delay_config` defaults: `automation_enabled=False`, `mule_candidates=[]`, `delay_hours_for_action_payout_delay=24`, `hold_duration_hours_default=72`, `honor_evaluate_action_tags=True`, `webhook_callback_url=""`
  - `async def sync_mule_holds_from_candidates(session, *, tenant_id, cfg, candidates) -> int` returns writes count
  - `build_payout_delay_payload` calls sync only if `automation_enabled` and `mule_candidates` non-empty
  - `release_payout_hold` returns `None` when store returns `None` (no synthetic success)
  - Delete `_mule_score_candidate` and SHA loop

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_list_with_automation_on_without_candidates_adds_no_synthetic(client, session):
    # PATCH automation_enabled=true, mule_candidates=[]
    r = await client.get("/v1/marketplace/payout-delay", params={"tenant_id": "nosynth"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "durable"
    assert body["payouts"] == [] or all(not str(p["payout_id"]).startswith("payout_") or p.get("held_by") == "evaluate" for p in body["payouts"])
    # stronger: after empty tenant, len==0
    assert body["payouts"] == []

@pytest.mark.asyncio
async def test_mule_candidates_create_durable_holds(client, session):
    await client.patch("/v1/marketplace/payout-delay/config", json={
        "tenant_id": "mule_real",
        "automation_enabled": True,
        "mule_score_hold_threshold": 50,
        "mule_candidates": [{
            "payout_id": "po_mule_1", "entity_id": "ent_m1", "mule_score": 90,
            "amount": 10.0, "currency": "USD",
        }],
    })
    r = await client.get("/v1/marketplace/payout-delay", params={"tenant_id": "mule_real"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "durable+automation"
    assert any(p["payout_id"] == "po_mule_1" for p in body["payouts"])
```

Update `test_mule_automation_writes_durable_holds` to use `mule_candidates` instead of SHA.

- [ ] **Step 2: Implement**

Remove `hashlib` / `_mule_score_candidate`. Implement `sync_mule_holds_from_candidates`. Optional graph enrich: if `os.environ.get("GRAPH_SERVICE_URL")` and http client available later — **YAGNI for this task unless already trivial; skip graph enrich if no existing ingress graph client** (document skip in report).

`update_payout_delay_config`: accept `mule_candidates`, `delay_hours_for_action_payout_delay`, `webhook_callback_url`, `honor_evaluate_action_tags`.

- [ ] **Step 3: PASS + commit**

```bash
git commit -m "$(cat <<'EOF'
feat: sync mule holds from explicit candidates only

EOF
)"
```

---

### Task 4: Auth compare_digest, release 404, webhooks

**Files:**
- Modify: `services/integration-ingress/src/integration_ingress/main.py`
- Modify: `services/integration-ingress/src/integration_ingress/marketplace_webhook_logs.py`
- Modify: `services/integration-ingress/src/integration_ingress/payout_delay_automation.py` (release None already Task 3)
- Modify: `services/integration-ingress/tests/test_payout_delay_durable.py`
- Create helper optional: `services/integration-ingress/src/integration_ingress/payout_hold_webhooks.py` if main.py gets too large — prefer small helper function in `marketplace_webhook_logs.py`: `async def notify_payout_hold_webhook(session, http, *, signal, callback_url, payload) -> None`

**Interfaces:**
- `_require_internal_or_admin` uses `secrets.compare_digest`
- Internal create: after `upsert_hold` → if materialized and `webhook_callback_url` on tenant config non-empty → record+deliver `signal=payout_hold`
- Release route: if release is None → HTTP 404; else webhook `payout_release`
- Startup lifespan or module log warning if `ingress_internal_token` empty

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.asyncio
async def test_internal_create_rejects_missing_and_bad_token(client, monkeypatch):
    monkeypatch.setenv("INGRESS_INTERNAL_TOKEN", "secret-tok")
    # reload settings if needed for the app under test
    r = await client.post("/v1/internal/marketplace/payout-holds", json={...minimal...})
    assert r.status_code == 401
    r2 = await client.post(..., headers={"X-Internal-Token": "wrong"})
    assert r2.status_code == 401

@pytest.mark.asyncio
async def test_release_missing_returns_404(client, session):
    r = await client.post("/v1/marketplace/payout-delay/missing_po/release", params={"tenant_id": "t404"})
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_internal_create_records_payout_hold_webhook(client, session, monkeypatch):
    # set token + PATCH webhook_callback_url to httpx mock URL / use respx
    ...
    assert any(log["signal"] == "payout_hold" for log in webhook_logs)
```

- [ ] **Step 2: Implement**

Extend `WebhookDeliveryStatus` / signal constants:

```python
SIGNAL_PAYOUT_HOLD = "payout_hold"
SIGNAL_PAYOUT_RELEASE = "payout_release"
```

`record_marketplace_block_webhook` already takes `signal` or hardcodes block — extend to accept `signal: str = SIGNAL_BLOCK`.

Wire create/release paths. Catch webhook exceptions and log.

- [ ] **Step 3: PASS + commit**

```bash
git commit -m "$(cat <<'EOF'
feat: payout hold webhooks and hardened internal auth

EOF
)"
```

---

### Task 5: Bridge failure metric + honor_evaluate_action_tags (optional gate)

**Files:**
- Modify: `services/decision-api/src/decision_api/payout_hold_bridge.py`
- Modify: `services/decision-api/src/decision_api/decision_outcome.py`
- Modify: `services/decision-api/tests/test_payout_hold_from_evaluate.py`

**Interfaces:**
- `maybe_create_payout_hold(..., metrics_inc: Callable | None = None)` on exception: `metrics_inc("payout_hold_bridge_failed")` if callable
- Pass `metrics_inc` from `schedule_decision_outcomes`
- Optional: if `metadata.get("honor_evaluate_action_tags") is False` skip — **prefer reading only evaluate metadata override**; full ingress config poll is out of scope. Document that tenant ingress `honor_evaluate_action_tags` is enforced when bridge payload includes it later — **for P1:** skip create when `metadata.get("honor_evaluate_action_tags") is False` OR when tags empty after filter. Ingress config flag unused by bridge in P1 (config still stored for UI); note in guide.

Actually match spec: honor flag on ingress config. Bridge cannot read ingress config without HTTP. **P1 decision:** bridge always honors tags when checkpoint matches; ingress `honor_evaluate_action_tags=False` is reserved for a future gateway. Document in guide as “config stored; evaluate bridge always honors when checkpoint+tags match (P1)”.

- [ ] **Step 1: Test metric on failure**

```python
@pytest.mark.asyncio
async def test_bridge_failure_increments_metric():
    calls = []
    class Boom:
        async def post(self, *a, **k):
            raise RuntimeError("down")
    await maybe_create_payout_hold(
        http=Boom(), base_url="http://x", token="t",
        payload={"tenant_id": "t", "payout_id": "p", "entity_id": "e", "status": "held"},
        metrics_inc=lambda m, **kw: calls.append(m),
    )
    assert "payout_hold_bridge_failed" in calls
```

- [ ] **Step 2: Implement + PASS + commit**

```bash
git commit -m "$(cat <<'EOF'
feat: count payout hold bridge failures

EOF
)"
```

---

### Task 6: Guide polish + verification suite

**Files:**
- Modify: `docs/docs/guides/vertical-packs-marketplace-delivery.md`
- Modify: `docs/superpowers/specs/2026-08-07-marketplace-p1-payout-hardening-design.md` — Status → Implemented (date)

- [ ] **Step 1: Run suite**

```bash
cd services/decision-api && python -m pytest tests/test_payout_hold_from_evaluate.py -q
cd ../integration-ingress && python -m pytest tests/test_payout_hold_store.py tests/test_payout_delay_durable.py tests/test_payout_delay_automation.py -q
```

Expected: all PASS

- [ ] **Step 2: Update guide** — delay vs hold table, webhook signals, mule_candidates, automation default off, release 404, PYTHONPATH note kept

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: marketplace P1 payout hardening guide and mark spec implemented

EOF
)"
```

---

## Spec coverage check

| Spec requirement | Task |
| --- | --- |
| hold vs delay status/hours | Task 1 |
| event_type=payout checkpoint | Task 1 |
| pending scheduled_release_at + materialized | Task 2 |
| Remove SHA mule; mule_candidates; automation default off | Task 3 |
| compare_digest; 401 tests; release 404; webhooks | Task 4 |
| Bridge failure metric | Task 5 |
| Guide + acceptance | Task 6 |
| Graph enrich optional | Task 3 YAGNI skip unless trivial |
| honor_evaluate_action_tags full ingress enforce | Deferred note in Task 5/guide |
| Track B/C | Out of plan |

## Placeholder scan

None intentional. Graph enrich explicitly YAGNI-skippable in Task 3.
