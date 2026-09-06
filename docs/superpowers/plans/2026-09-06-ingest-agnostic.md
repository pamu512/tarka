# Ingest Agnostic (P-ing1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow-listed string `event_type` (seed six ∪ env ∪ tenant overlay) and omitted SDK bools stay missing — no invented `false`.

**Architecture:** Shared-core validates shape + allow-list. Decision-api stores tenant extras and checks them on evaluate. Event-ingest uses seed ∪ env (no Postgres overlay this PR). Feature snapshot already copies payload as-is; goldens/demo stop shipping invented `false`. `device_signals` stays `is_true`.

**Tech Stack:** Python (shared-core, decision-api, event-ingest), Alembic, FastAPI, existing JSON packs.

**Spec:** [2026-09-06-ingest-agnostic-design.md](../specs/2026-09-06-ingest-agnostic-design.md)

**Branch:** `honesty/ingest-agnostic` stacked on `#378` / `feat/desk-demo-vs-product`

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- No `rate` / `baseline_ratio`. No new Rust atom. No `desk_provision.json`.
- Demo PUT 403. No Tarka OSS / third-party desk names in new copy.
- One public evaluate-shaped contract. Overlay store down on evaluate → seed ∪ env only (log once).

---

## File map

| File | Role |
|------|------|
| Modify: `packages/shared-core/tarka_shared/ingest_contract_v1.py` | Shape, env parse, allow-list, envelope check takes `allowed` |
| Create: `services/decision-api/src/decision_api/data/event_types_v1.json` | Seed six |
| Modify: `services/decision-api/src/decision_api/schemas.py` | `event_type: str` (shape only) |
| Modify: `services/decision-api/src/decision_api/evaluate/pipeline.py` | Allow-list after tenant known; `event_type.value` → string |
| Create: event_types store + Alembic `20260906_011` + `event_type_api.py` | Overlay + GET/PUT |
| Modify: event-ingest contract | Seed ∪ env |
| Modify: goldens + `ingest-contract-v1.md` + device_signals tests | Missing ≠ false |

---

### Task 1: Shared-core helpers

**Files:**
- Modify: `packages/shared-core/tarka_shared/ingest_contract_v1.py`
- Modify: `packages/shared-core/tests/test_ingest_contract_v1.py`

**Interfaces:**
- Produces: `SEED_EVENT_TYPES` (alias `VALID_EVENT_TYPES` kept as the same frozenset literal for `schema_registry_compat.py` AST); `EVENT_TYPE_RE`; `validate_event_type_shape(name) -> str`; `parse_env_event_types(raw) -> frozenset[str]`; `allowed_event_types(overlay, env) -> frozenset[str]`; `validate_required_envelope_fields(raw, allowed=None)` — `allowed` default `SEED_EVENT_TYPES`

- [ ] **Step 1: Failing tests** in `test_ingest_contract_v1.py`:

```python
from tarka_shared.ingest_contract_v1 import (
    SEED_EVENT_TYPES,
    allowed_event_types,
    parse_env_event_types,
    validate_event_type_shape,
    validate_required_envelope_fields,
    IngestContractV1Error,
)

def test_shape_rejects_bad():
    for bad in ("", "EventCount", "tx_pay", "Refund"):
        try:
            validate_event_type_shape(bad)
        except ValueError:
            continue
        raise AssertionError(bad)

def test_env_and_overlay_allow_refund():
    env = parse_env_event_types("refund, not-a-type, login")
    assert "refund" in env
    assert "not-a-type" not in env
    allowed = allowed_event_types(frozenset({"payout"}), env)
    assert "refund" in allowed and "payout" in allowed and "payment" in allowed

def test_envelope_accepts_allowed_refund():
    out = validate_required_envelope_fields(
        {"tenant_id": "t", "entity_id": "e", "event_type": "refund"},
        allowed=SEED_EVENT_TYPES | frozenset({"refund"}),
    )
    assert out["event_type"] == "refund"

def test_envelope_rejects_wire_without_allow():
    with pytest.raises(IngestContractV1Error) as exc:
        validate_required_envelope_fields(
            {"tenant_id": "t", "entity_id": "e", "event_type": "wire"}
        )
    assert exc.value.reason_codes == ["ingest_event_type_invalid"]
```

- [ ] **Step 2:** Run `cd packages/shared-core && PYTHONPATH=. python3 -m pytest tests/test_ingest_contract_v1.py -q` — expect FAIL
- [ ] **Step 3:** Implement helpers. Keep `VALID_EVENT_TYPES = frozenset({...six...})` as a **literal** (CI AST). `SEED_EVENT_TYPES = VALID_EVENT_TYPES`.
- [ ] **Step 4:** Tests PASS
- [ ] **Step 5:** Commit `feat: allow-list event_type in ingest contract`

---

### Task 2: Evaluate + ingest accept allow-listed strings

**Files:**
- Modify: `services/decision-api/src/decision_api/schemas.py` — `event_type: str` + shape validator (accept `EventType` enum instances)
- Modify: pipeline / enrichment / main — `body.event_type.value` → `body.event_type` (str)
- Modify: `services/event-ingest/src/event_ingest/ingest_contract.py` and `dynamic.py` — seed ∪ `TARKA_EVENT_TYPES`
- Test: schemas + a small evaluate/ingest 422 test

**Interfaces:**
- Consumes: `validate_event_type_shape`, `allowed_event_types`, `parse_env_event_types`
- Evaluate allow-list = seed ∪ env ∪ overlay (overlay load fail → seed ∪ env)

- [ ] **Step 1:** Test `EvaluateRequest(event_type="refund", ...)` parses shape; `event_type="Refund"` 422. Pipeline/evaluate 422 when `refund` not allowed; 200 path tested later with env.
- [ ] **Step 2:** FAIL
- [ ] **Step 3:** Implement. Add `require_allowed_event_type(tenant_id, name)` in decision-api that loads overlay or empty and raises HTTP 422 `{error, reason_codes: [ingest_event_type_invalid]}` matching ingest.
- [ ] **Step 4:** PASS
- [ ] **Step 5:** Commit `feat: evaluate and ingest accept allow-listed event_type`

---

### Task 3: Overlay store + HTTP

**Files:**
- Create: `event_types_v1.json`, model, store, Alembic `20260906_011` (revises `20260905_010`), `event_type_api.py` router prefix `/v1/event-types`
- Register router in `main.py` like `field_api`
- Tests like `test_field_api.py` (demo PUT 403, GET union, PUT overlay then evaluate `refund`)

- [ ] **Step 1:** Failing API tests
- [ ] **Step 2:** FAIL
- [ ] **Step 3:** Implement (copy field_api demo-403 / tenant strip / analyst role)
- [ ] **Step 4:** PASS
- [ ] **Step 5:** Commit `feat: tenant event type overlay`

---

### Task 4: Missing ≠ false + docs

**Files:**
- Modify: `contracts/golden/evaluate-request-minimal.v1.json`, `device-context-web.v1.json` — omit invented false SDK bools
- Modify: `services/decision-api/tests/test_device_signals_bind.py` — `is_bot` omitted / false / true
- Modify: `docs/docs/guides/ingest-contract-v1.md`
- Grep demo/golden for `"is_bot": false` and omit unless the fixture is “SDK sent false”
- `merge_device_context_into_features`: skip non-bool for `_SIGNAL_TAG_MAP` keys (same as integrity)

- [ ] **Step 1:** Tests for sdk_bot omitted/false/true
- [ ] **Step 2:** FAIL if merge copies `"yes"`
- [ ] **Step 3:** Goldens + docs + merge skip
- [ ] **Step 4:** `test_device_signals_bind.py` + ingest contract + field/author catalog still pass
- [ ] **Step 5:** Commit `fix: omit invented SDK false; document allow-listed event_type`
