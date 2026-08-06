# Loyalty Economics Multi-Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship shadow multi-gate loyalty economics (dispatch / redeem / order) with hygiene + program-config prerequisites, never denying the order from this path alone.

**Architecture:** Pure `loyalty_economics.py` engine consumes feed snapshot + program config (+ optional cluster ids); evaluate pipeline attaches `loyalty_economics_gates` to audit/inference and advisory tags only. Host systems enforce benefit suppression. Layer-3 spend derive is optional (`partial_derived`).

**Tech Stack:** Python 3 / FastAPI decision-api, pytest via `services/decision-api/.venv`, evaluate pipeline patterns matching `location_cohort_evidence.py`.

**Spec:** `docs/superpowers/specs/2026-08-06-loyalty-economics-multi-gate-design.md`

## Global Constraints

- H1: No `eligible: true` on partial/stale/missing feeds or missing config (`eligible` must be `null`).
- H8: Loyalty economics alone must not map to evaluate `deny` / enforcement `block`.
- H9: Gates `dispatch`, `redeem`, `order` are independent.
- H10: Scope `program` | `coupon_id` | `offer_class`.
- Unit: `cluster` when `cluster_entity_ids` length ≥ 2, else `entity`.
- Schema id: `tarka.loyalty_economics_gates/v1`.
- Location signals out of this path (no geo inputs).
- Use decision-api `.venv` for pytest: `PYTHONPATH=src:../shared:../../packages/shared-core:../.. .venv/bin/python -m pytest ...`
- Commit only task files; leave unrelated WIP unstaged.

## File map

| File | Role |
| --- | --- |
| `services/decision-api/src/decision_api/loyalty_economics.py` | Pure engine + types |
| `services/decision-api/tests/test_loyalty_economics_gates.py` | Unit + evaluate contract |
| `services/decision-api/src/decision_api/evaluate/pipeline.py` | Wire snapshot + tags |
| `docs/docs/guides/loyalty-abuse-model-prerequisites.md` | Hygiene contract examples |
| `rules/loyalty_program_config.example.json` | Example Layer-2 config |

---

### Task 0: Example config + prerequisites examples

**Files:**
- Create: `rules/loyalty_program_config.example.json`
- Modify: `docs/docs/guides/loyalty-abuse-model-prerequisites.md`

- [ ] **Step 1: Write example program config**

```json
{
  "schema_id": "tarka.loyalty_program_config/v1",
  "tenant_id": "demo",
  "program_id": "default",
  "config_version": "1",
  "effective_at": "2026-08-01T00:00:00Z",
  "acquisition_cost_minor": 2500,
  "retention_cost_minor": 500,
  "target_loyalty_ltv_ratio": 0.12,
  "ineligible_above_ratio": 0.25,
  "restore_at_or_below_ratio": 0.12,
  "min_dwell_seconds": 86400,
  "target_program_roi": 1.5,
  "window": "trailing_90d",
  "velocity_window": "trailing_7d",
  "new_member_grace_days": 14,
  "vip_entity_ids": [],
  "max_feed_age_seconds": 86400
}
```

- [ ] **Step 2: Add feed snapshot example + multi-gate status table to prerequisites guide** (field lists already exist; add JSON snapshot example and gate vector pointer to design).

- [ ] **Step 3: Commit**

```bash
git add rules/loyalty_program_config.example.json docs/docs/guides/loyalty-abuse-model-prerequisites.md
git commit -m "docs: loyalty program config example and hygiene gate contract"
```

---

### Task 1: Pure engine — completeness, metrics, gate vector

**Files:**
- Create: `services/decision-api/src/decision_api/loyalty_economics.py`
- Test: `services/decision-api/tests/test_loyalty_economics_gates.py`

**Interfaces:**
- Produces:
  - `SCHEMA_ID = "tarka.loyalty_economics_gates/v1"`
  - `evaluate_loyalty_economics(*, entity_id: str, feed_snapshot: dict | None, program_config: dict | None, cluster_entity_ids: list[str] | None = None, scope: dict | None = None, now: datetime | None = None, prior_gate_state: dict | None = None) -> dict`
  - Return always includes `schema_id`, `status`, `gates.dispatch|redeem|order` each with `eligible` (`bool|None`), `status`, `reasons`, `as_of`; `policy.order_decision_untouched: True`

- [ ] **Step 1: Write failing tests**

```python
"""Loyalty economics multi-gate — hygiene, thresholds, non-deny."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from decision_api.loyalty_economics import SCHEMA_ID, evaluate_loyalty_economics


def _cfg(**over):
    base = {
        "schema_id": "tarka.loyalty_program_config/v1",
        "program_id": "default",
        "config_version": "1",
        "effective_at": "2026-01-01T00:00:00Z",
        "acquisition_cost_minor": 2500,
        "retention_cost_minor": 500,
        "target_loyalty_ltv_ratio": 0.12,
        "ineligible_above_ratio": 0.25,
        "restore_at_or_below_ratio": 0.12,
        "min_dwell_seconds": 86400,
        "window": "trailing_90d",
        "velocity_window": "trailing_7d",
        "new_member_grace_days": 0,
        "vip_entity_ids": [],
        "max_feed_age_seconds": 86400,
    }
    base.update(over)
    return base


def _complete_feeds(entity_id="e1", loyalty_cost=400, ltv_orders=1000, refunds=0, as_of=None):
    as_of = as_of or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "as_of": as_of,
        "orders": [
            {
                "entity_id": entity_id,
                "order_id": "o1",
                "ts": as_of,
                "amount_minor": ltv_orders,
                "currency": "USD",
                "status": "paid",
            }
        ],
        "refunds": (
            []
            if refunds == 0
            else [
                {
                    "entity_id": entity_id,
                    "order_id": "o1",
                    "ts": as_of,
                    "amount_minor": refunds,
                    "currency": "USD",
                }
            ]
        ),
        "loyalty_ledger": [
            {
                "entity_id": entity_id,
                "ts": as_of,
                "direction": "burn",
                "value_minor": loyalty_cost,
                "program_id": "default",
            }
        ],
        "lifecycle": [
            {
                "entity_id": entity_id,
                "created_at": "2025-01-01T00:00:00Z",
                "last_active_at": as_of,
            }
        ],
    }


def test_schema_and_missing_feeds():
    out = evaluate_loyalty_economics(
        entity_id="e1", feed_snapshot=None, program_config=_cfg()
    )
    assert out["schema_id"] == SCHEMA_ID
    assert out["status"] == "feeds_missing"
    assert out["gates"]["order"]["eligible"] is None
    assert out["policy"]["order_decision_untouched"] is True


def test_incomplete_without_ledger():
    snap = _complete_feeds()
    del snap["loyalty_ledger"]
    out = evaluate_loyalty_economics(
        entity_id="e1", feed_snapshot=snap, program_config=_cfg()
    )
    assert out["status"] == "feeds_incomplete"
    assert out["gates"]["dispatch"]["eligible"] is None


def test_config_missing():
    out = evaluate_loyalty_economics(
        entity_id="e1", feed_snapshot=_complete_feeds(), program_config=None
    )
    assert out["status"] == "config_missing"


def test_ratio_breach_order_ineligible_dispatch_may_differ():
    # loyalty 400 / LTV 1000 = 0.4 > 0.25
    out = evaluate_loyalty_economics(
        entity_id="e1",
        feed_snapshot=_complete_feeds(loyalty_cost=400, ltv_orders=1000),
        program_config=_cfg(),
        scope={"kind": "program", "id": "default"},
    )
    assert out["status"] in ("ok", "partial_derived")
    assert out["metrics"]["loyalty_ltv_ratio"] == 0.4
    assert out["gates"]["order"]["eligible"] is False
    assert out["gates"]["order"]["status"] == "ok"
    # v1 default policy: dispatch also ineligible on ratio breach (churn weight same)
    assert out["gates"]["dispatch"]["eligible"] is False


def test_healthy_ratio_all_eligible():
    out = evaluate_loyalty_economics(
        entity_id="e1",
        feed_snapshot=_complete_feeds(loyalty_cost=50, ltv_orders=1000),
        program_config=_cfg(),
    )
    assert out["gates"]["order"]["eligible"] is True
    assert out["gates"]["redeem"]["eligible"] is True
    assert out["gates"]["dispatch"]["eligible"] is True


def test_hysteresis_requires_dwell():
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    # Currently healthy ratio but prior ineligible without enough dwell
    prior = {
        "ineligible_since": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "restore_band_since": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    out = evaluate_loyalty_economics(
        entity_id="e1",
        feed_snapshot=_complete_feeds(loyalty_cost=50, ltv_orders=1000, as_of=now.isoformat().replace("+00:00", "Z")),
        program_config=_cfg(min_dwell_seconds=86400),
        now=now,
        prior_gate_state=prior,
    )
    assert out["gates"]["order"]["eligible"] is False
    assert any("dwell" in r for r in out["gates"]["order"]["reasons"])


def test_vip_escape():
    out = evaluate_loyalty_economics(
        entity_id="vip1",
        feed_snapshot=_complete_feeds(entity_id="vip1", loyalty_cost=900, ltv_orders=1000),
        program_config=_cfg(vip_entity_ids=["vip1"]),
    )
    assert out["gates"]["order"]["eligible"] is True
    assert any("vip" in r for r in out["gates"]["order"]["reasons"])


def test_cluster_unit_when_peers():
    out = evaluate_loyalty_economics(
        entity_id="e1",
        feed_snapshot=_complete_feeds(),
        program_config=_cfg(),
        cluster_entity_ids=["e1", "e2"],
    )
    assert out["unit"] == "cluster"
```

- [ ] **Step 2: Run tests — expect fail (module missing)**

```bash
cd services/decision-api && PYTHONPATH=src:../shared:../../packages/shared-core:../.. .venv/bin/python -m pytest tests/test_loyalty_economics_gates.py -q
```

Expected: import / collection error.

- [ ] **Step 3: Implement `loyalty_economics.py`**

Minimal behavior:

1. Validate config present with required keys → else `config_missing`.
2. Validate feed snapshot has non-empty `orders`, `loyalty_ledger`, `lifecycle` keys (lists present; `refunds` key present even if empty) → else `feeds_missing` / `feeds_incomplete`.
3. Check `as_of` age vs `max_feed_age_seconds` → `stale`.
4. Roll up LTV = sum(paid orders) − sum(refunds) for entity (and cluster ids if provided — include rows matching any id).
5. Loyalty cost = sum of ledger `value_minor` where direction in (`burn`, `earn` counts as cost if negative convention — v1: **burn + earn both add to loyalty_cost_minor** using abs for earn face value when `value_minor` set; simplest v1: sum `value_minor` for all ledger rows).
6. `loyalty_ltv_ratio = loyalty_cost / ltv` if ltv > 0 else treat as breach if loyalty_cost > 0.
7. Order velocity: count orders in `velocity_window` (parse as trailing_Nd days; default 7).
8. Churn proxy: lifecycle `created_at` within 30d and order count ≤ 1 → flag reason `churn_proxy_new_low_repeat` (informational; v1 does not alone flip gates unless ratio also breaches — keep YAGNI: attach to reasons when true).
9. Gate policy v1 (documented in module docstring):
   - If VIP → all gates eligible true, reason `vip_allowlist`.
   - If in new_member_grace → all eligible true, reason `new_member_grace`.
   - If ratio > `ineligible_above_ratio` → all three gates eligible false, reason `loyalty_ltv_above_threshold` (independent structure preserved; same outcome ok for v1 defaults).
   - If ratio ≤ `restore_at_or_below_ratio`: eligible true only if no prior ineligible **or** `restore_band_since` dwell ≥ `min_dwell_seconds`; else false with `dwell_not_met`.
   - If between restore and ineligible thresholds: keep prior ineligibility if `prior_gate_state.ineligible_since` set; else eligible true (hysteresis band).
10. `partial_derived` when status would be ok and spend feed absent (always in v1 without spend key).
11. Always `policy.order_decision_untouched: True`.

- [ ] **Step 4: Pytest pass**

```bash
cd services/decision-api && PYTHONPATH=src:../shared:../../packages/shared-core:../.. .venv/bin/python -m pytest tests/test_loyalty_economics_gates.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add services/decision-api/src/decision_api/loyalty_economics.py services/decision-api/tests/test_loyalty_economics_gates.py
git commit -m "feat: loyalty economics multi-gate engine with hygiene prerequisites"
```

---

### Task 2: Evaluate pipeline wire (shadow advice, non-deny)

**Files:**
- Modify: `services/decision-api/src/decision_api/evaluate/pipeline.py`
- Modify: `services/decision-api/tests/test_loyalty_economics_gates.py` (add evaluate contract tests)

**Interfaces:**
- Consumes: `evaluate_loyalty_economics` from Task 1
- Reads `body.metadata.get("loyalty_feed_snapshot")`, `body.metadata.get("loyalty_program_config")`, optional `body.metadata.get("loyalty_cluster_entity_ids")`, `body.metadata.get("loyalty_scope")`, `body.metadata.get("loyalty_prior_gate_state")`
- Writes `payload_snapshot["loyalty_economics_gates"]` when metadata contains config **or** feed snapshot (attempt evaluate; status reflects gaps)
- Appends advisory tags only when gate `status=="ok"` and `eligible is False`

- [ ] **Step 1: Failing evaluate contract tests**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Reuse patterns from test_location_cohort_evidence evaluate test:
# mock heavy deps; POST /v1/decisions/evaluate with metadata feeds+config
# assert audit/response snapshot includes loyalty_economics_gates
# assert decision is allow when only loyalty economics would fire (no other deny rules)


@pytest.mark.asyncio
async def test_evaluate_attaches_loyalty_gates_without_deny(monkeypatch):
    # Implementation: follow test_evaluate_surfaces_cohort_partner_evidence style
    # in test_location_cohort_evidence.py — patch redis/graph/ml as needed.
    # Body metadata includes _complete_feeds() + _cfg().
    # Assert "loyalty_economics_gates" in payload_snapshot or response inference/audit.
    # Assert decision != "deny" solely from loyalty tags.
    pass
```

Replace `pass` with a real test modeled on `test_location_cohort_evidence.py::test_evaluate_surfaces_cohort_partner_evidence` (copy fixture structure; assert gates key + allow).

- [ ] **Step 2: Wire pipeline**

Near `build_location_cohort_evidence` usage:

```python
from decision_api.loyalty_economics import evaluate_loyalty_economics

# After tags/inference assembled, before audit persist:
_meta = body.metadata if isinstance(body.metadata, dict) else {}
if _meta.get("loyalty_feed_snapshot") is not None or _meta.get("loyalty_program_config") is not None:
    _loyalty_gates = evaluate_loyalty_economics(
        entity_id=str(body.entity_id),
        feed_snapshot=_meta.get("loyalty_feed_snapshot"),
        program_config=_meta.get("loyalty_program_config"),
        cluster_entity_ids=_meta.get("loyalty_cluster_entity_ids"),
        scope=_meta.get("loyalty_scope"),
        prior_gate_state=_meta.get("loyalty_prior_gate_state"),
    )
    snap_extra["loyalty_economics_gates"] = _loyalty_gates
    for gname, tag in (
        ("dispatch", "loyalty:dispatch_ineligible"),
        ("redeem", "loyalty:redeem_ineligible"),
        ("order", "loyalty:order_benefit_ineligible"),
    ):
        g = (_loyalty_gates.get("gates") or {}).get(gname) or {}
        if g.get("status") == "ok" and g.get("eligible") is False:
            if tag not in signal_tags:
                signal_tags.append(tag)
# Do NOT change decision/recommended_action from these tags in this task.
```

Place `snap_extra` / `signal_tags` names to match actual pipeline locals (read file; use existing snapshot dict).

- [ ] **Step 3: Pytest**

```bash
cd services/decision-api && PYTHONPATH=src:../shared:../../packages/shared-core:../.. .venv/bin/python -m pytest tests/test_loyalty_economics_gates.py -q
```

- [ ] **Step 4: Commit**

```bash
git add services/decision-api/src/decision_api/evaluate/pipeline.py services/decision-api/tests/test_loyalty_economics_gates.py
git commit -m "feat: attach shadow loyalty economics gates on evaluate"
```

---

### Task 3: Independent gate policy knobs + docs claim language

**Files:**
- Modify: `services/decision-api/src/decision_api/loyalty_economics.py`
- Modify: `services/decision-api/tests/test_loyalty_economics_gates.py`
- Modify: `docs/docs/guides/loyalty-abuse-model-prerequisites.md`
- Modify: `docs/superpowers/canvases/maturity-4-0-regrade.canvas.tsx` (S9 note: engine landed, feeds still prerequisite)

**Interfaces:**
- Config optional `gate_policies`: `{ "dispatch": { "ratio_weight": 1.0, "churn_flips": true }, "redeem": {...}, "order": {...} }`
- v1: if `churn_flips` true and churn proxy and ratio > target (not only ineligible_above), dispatch may be false while order still true when ratio ≤ ineligible_above — prove independence in test

- [ ] **Step 1: Test independence**

```python
def test_dispatch_ineligible_order_eligible_with_policy():
    # ratio 0.15 — between target 0.12 and ineligible 0.25
    # churn_proxy true (new account low repeat)
    # gate_policies: dispatch.churn_flips true; order only flips above ineligible_above
    cfg = _cfg(
        gate_policies={
            "dispatch": {"churn_flips": True},
            "redeem": {"churn_flips": False},
            "order": {"churn_flips": False},
        }
    )
    snap = _complete_feeds(loyalty_cost=150, ltv_orders=1000)
    snap["lifecycle"] = [{
        "entity_id": "e1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "last_active_at": snap["as_of"],
    }]
    out = evaluate_loyalty_economics(
        entity_id="e1", feed_snapshot=snap, program_config=cfg
    )
    assert out["gates"]["order"]["eligible"] is True
    assert out["gates"]["dispatch"]["eligible"] is False
```

- [ ] **Step 2: Implement gate_policies branch; update docs; canvas S9 line → “engine+contract landed; tenant feeds still required”**

- [ ] **Step 3: Pytest + commit**

```bash
git commit -m "feat: independent loyalty gate policies for dispatch vs order"
```

---

### Task 4: Guardrail test — tags never alone force deny

**Files:**
- Modify: `services/decision-api/tests/test_loyalty_economics_gates.py`

- [ ] **Step 1: Test `derive_recommended_action` / decision path**

Assert helper or pure check: presence of `loyalty:order_benefit_ineligible` in tags with decision allow score path does not flip to deny in `derive_recommended_action` (call existing function with those tags only → not deny). If current derive ignores unknown tags, assert that explicitly.

```python
from decision_api.inference_build import derive_recommended_action

def test_loyalty_tags_do_not_derive_deny():
    rec = derive_recommended_action(
        "allow",
        ["loyalty:order_benefit_ineligible", "loyalty:dispatch_ineligible"],
        {"score": 0.1},
    )
    assert "deny" not in str(rec).lower()
```

Adjust to actual `derive_recommended_action` signature from `inference_build.py`.

- [ ] **Step 2: Commit**

```bash
git commit -m "test: loyalty economics tags cannot alone derive deny"
```

---

## Spec coverage

| Spec requirement | Task |
| --- | --- |
| Hygiene feeds prerequisite / incomplete | Task 1 |
| Program config thresholds | Task 0–1 |
| Hybrid partial_derived | Task 1 |
| Multi-gate dispatch/redeem/order | Task 1, 3 |
| No order deny | Task 2, 4 |
| Hysteresis dwell | Task 1 |
| VIP / grace | Task 1 |
| Cluster vs entity | Task 1 |
| Pipeline audit | Task 2 |
| Docs / claim language | Task 0, 3 |
| Independent gates | Task 3 |

**Open left to hosts (out of plan):** CRM dispatch enforcement, wallet redeem API, checkout suppress — advice contract only.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-06-loyalty-economics-multi-gate.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks

**2. Inline Execution** — this session with executing-plans checkpoints

Which approach?
