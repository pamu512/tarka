# Observe brain wire Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scout and the recommender read leftover helpfulness before they publish; leftover-extra FP / no-lift kills AI shadow drafts and silences the next pack.

**Architecture:** Pure critic on the leftover HIL GET payload (`leftover_promote_gate.helpfulness` + `rule_precision_after_labels`). GET stays read-only. Kill + durable fingerprint land on the leftover-HIL tick / y_label merge / scout-pack host side (same clock as auto-promote and slip park). Scout still POSTs `mode=shadow` only. Do not re-join extras in shadow_agent.

**Tech Stack:** decision-api FastAPI, existing `y_label_store` + leftover HIL + `rule_precision_after_labels`, shadow_agent publisher, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-observe-brain-wire-design.md`

**Not this plan:** Live-rule slip (already shipped). Draft knobs (B). VisualRuleBuilder. `/v1/brain`. Scout writing `mode=active`.

## Global Constraints

- Rust packs remain sole allow/deny. Evaluate never waits on graph.
- GET `/v1/calibration/shadow-promote-gate` must not write pack files or the killed set.
- Same leftover-extra FP / no-lift rules as leftover_promote_gate. No second label math.
- Do not drop publish solely for leftover **cost** blockers (`leftover_sla_breached`, `leftover_add_over_cap`, `leftover_claimer_ack_required`).
- Scout / LLM cannot set `mode=active`, Promote, or force-live. `PACK_AUTHOR.md` hard stops stay.
- Kill / auto-promote stay `is_ai_authored` only. Slip drafts (`authored_by=slip_critic`) stay up.
- Scout does not promote from `live_rule_slip`. Clobber 409 `slip_draft_exists` already exists — do not remove it.
- Do not commit unless the user asks.
- CI decision-api: `cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_brain_wire.py tests/test_brain_wire_api.py tests/test_shadow_promote_gate_api.py -q`
- CI shadow-agent: `cd services/shadow_agent && PYTHONPATH=.:../shared pytest tests/test_scout_burst_publish_loop.py tests/test_brain_wire_publish.py -q`

## File map

| File | Responsibility |
|------|----------------|
| `services/decision-api/src/decision_api/brain_wire.py` | Verdict, strip rules, kill helpers, durable fingerprints |
| `services/decision-api/tests/test_brain_wire.py` | Pure critic + kill file |
| `services/decision-api/src/decision_api/leftover_promote_gate.py` | Fold `rule_precision_after_labels` into compute |
| `services/decision-api/src/decision_api/calibration_api.py` | Return precision on GET; tick kill after auto-promote |
| `services/decision-api/src/decision_api/rule_api.py` | Tick kill; scout-pack refuse if critic drops |
| `services/decision-api/tests/test_brain_wire_api.py` | GET no-write, tick kill, scout 409 killed fingerprint |
| `services/decision-api/src/decision_api/recommend_api.py` | Filter `/analyze` with same rule-FP stop + `dropped` |
| `services/shadow_agent/scout_pack_publisher.py` | GET gate before POST |
| `services/shadow_agent/tests/test_brain_wire_publish.py` | Publisher drops |
| `services/shadow_agent/PACK_AUTHOR.md` | Hard stops 8–9 |

---

### Task 1: Pure critic (`brain_wire_verdict`)

**Files:**
- Create: `services/decision-api/src/decision_api/brain_wire.py`
- Test: `services/decision-api/tests/test_brain_wire.py`

**Interfaces:**
- Consumes: leftover `helpfulness` dict; `rule_precision_after_labels` payload; proposed rule ids; `fp_cap: float`
- Produces:
  - `HELPFULNESS_DROP = frozenset({"leftover_extras_fp_over_cap", "leftover_extras_no_lift"})`
  - `brain_wire_verdict(helpfulness, precision, *, proposed_rule_ids: Sequence[str], fp_cap: float) -> dict`

Return shape:

```
{
  "publish_allowed": bool,
  "reason": str | None,   # leftover_extras_fp_over_cap | leftover_extras_no_lift | rule_fp_over_cap | None
  "keep_rule_ids": list[str],
  "stamp_underpowered": bool,
  "should_kill": bool,    # True iff a helpfulness drop blocker is present
}
```

- [ ] **Step 1: Failing tests**

```python
from decision_api.brain_wire import HELPFULNESS_DROP, brain_wire_verdict


def _h(*, blockers=(), underpowered=False, labeled=5, tp=0, fp=5):
    return {
        "blockers": list(blockers),
        "underpowered": underpowered,
        "labeled_extras": labeled,
        "extra_tp": tp,
        "extra_fp": fp,
    }


def test_fp_over_cap_drops_and_kills():
    v = brain_wire_verdict(
        _h(blockers=["leftover_extras_fp_over_cap"]),
        {"rules": []},
        proposed_rule_ids=["r1"],
        fp_cap=0.4,
    )
    assert v["publish_allowed"] is False
    assert v["reason"] == "leftover_extras_fp_over_cap"
    assert v["should_kill"] is True


def test_no_lift_drops_and_kills():
    v = brain_wire_verdict(
        _h(blockers=["leftover_extras_no_lift"]),
        {"rules": []},
        proposed_rule_ids=["r1"],
        fp_cap=0.4,
    )
    assert v["reason"] == "leftover_extras_no_lift"
    assert v["should_kill"] is True


def test_sla_cost_blocker_does_not_drop():
    v = brain_wire_verdict(
        _h(blockers=["leftover_sla_breached"], underpowered=True, labeled=0, tp=0, fp=0),
        {"rules": []},
        proposed_rule_ids=["r1"],
        fp_cap=0.4,
    )
    assert v["publish_allowed"] is True
    assert v["should_kill"] is False
    assert v["stamp_underpowered"] is True


def test_rule_fp_strips_then_empty_drops():
    precision = {
        "rules": [
            {"rule_id": "r1", "enough_support": True, "fp_rate": 0.8},
            {"rule_id": "r2", "enough_support": False, "fp_rate": 0.9},
        ]
    }
    v = brain_wire_verdict(_h(underpowered=True, labeled=0), precision, proposed_rule_ids=["r1", "r2"], fp_cap=0.4)
    assert v["keep_rule_ids"] == ["r2"]
    v2 = brain_wire_verdict(_h(underpowered=True, labeled=0), precision, proposed_rule_ids=["r1"], fp_cap=0.4)
    assert v2["publish_allowed"] is False
    assert v2["reason"] == "rule_fp_over_cap"
    assert v2["should_kill"] is False


def test_underpowered_stamps_and_publishes():
    v = brain_wire_verdict(_h(underpowered=True, labeled=3, tp=1, fp=2), {"rules": []}, proposed_rule_ids=["r1"], fp_cap=0.4)
    assert v["publish_allowed"] is True
    assert v["stamp_underpowered"] is True
    assert v["should_kill"] is False
```

- [ ] **Step 2: Run** `cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_brain_wire.py -q` — expected FAIL import

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

from typing import Any, Mapping, Sequence

HELPFULNESS_DROP = frozenset({"leftover_extras_fp_over_cap", "leftover_extras_no_lift"})


def brain_wire_verdict(
    helpfulness: Mapping[str, Any] | None,
    precision: Mapping[str, Any] | None,
    *,
    proposed_rule_ids: Sequence[str],
    fp_cap: float,
) -> dict[str, Any]:
    h = helpfulness if isinstance(helpfulness, Mapping) else {}
    blockers = {str(b) for b in (h.get("blockers") or []) if b}
    drop = next((b for b in ("leftover_extras_fp_over_cap", "leftover_extras_no_lift") if b in blockers), None)
    if drop:
        return {
            "publish_allowed": False,
            "reason": drop,
            "keep_rule_ids": [],
            "stamp_underpowered": False,
            "should_kill": True,
        }
    keep: list[str] = []
    rules = {str(r.get("rule_id") or ""): r for r in ((precision or {}).get("rules") or []) if isinstance(r, Mapping)}
    for rid in proposed_rule_ids:
        token = str(rid or "").strip()
        if not token:
            continue
        row = rules.get(token) or {}
        if bool(row.get("enough_support")) and float(row.get("fp_rate") or 0) > fp_cap:
            continue
        keep.append(token)
    if proposed_rule_ids and not keep:
        return {
            "publish_allowed": False,
            "reason": "rule_fp_over_cap",
            "keep_rule_ids": [],
            "stamp_underpowered": False,
            "should_kill": False,
        }
    return {
        "publish_allowed": True,
        "reason": None,
        "keep_rule_ids": keep,
        "stamp_underpowered": bool(h.get("underpowered")),
        "should_kill": False,
    }
```

- [ ] **Step 4: Run** same command — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 2: Fold `rule_precision_after_labels` onto GET (no write)

**Files:**
- Modify: `services/decision-api/src/decision_api/leftover_promote_gate.py` (`compute_desk_and_leftover_gates` return)
- Modify: `services/decision-api/src/decision_api/calibration_api.py` (`shadow_promote_gate` return)
- Test: `services/decision-api/tests/test_shadow_promote_gate_api.py`

**Interfaces:**
- Produces: GET body includes `rule_precision_after_labels` (same function, same 500-row export + y_label join already used for leftover extras). Empty rules when no tenant / scan failed.

- [ ] **Step 1:** In `test_shadow_promote_gate_api.py` assert `"rule_precision_after_labels" in body` and `body["rule_precision_after_labels"]["schema_id"] == "tarka.rule_precision_after_labels/v1"` on the existing no-tenant GET test.

- [ ] **Step 2: Run** that test — expected FAIL missing key

- [ ] **Step 3:** In `compute_desk_and_leftover_gates`, after y maps exist, build labeled rows from the same `cc_rows` / slip_rows already scanned (reuse the labeled join leftover HIL uses: set `y_label` from `by_trace` then `by_entity`). Call `rule_precision_after_labels(labeled_rows)`. Return it on the gates dict. GET copies `gates["rule_precision_after_labels"]`. GET must not call kill or park.

- [ ] **Step 4: Run** `cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_shadow_promote_gate_api.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless asked.

---

### Task 3: Durable kill + `maybe_kill_leftover_fp_shadows`

**Files:**
- Modify: `services/decision-api/src/decision_api/brain_wire.py`
- Test: `services/decision-api/tests/test_brain_wire.py`

**Interfaces:**
- Consumes: leftover helpfulness blockers; loaded packs
- Produces:
  - `killed_path(tenant_id) -> Path` next to `y_label_store` (`killed_scout_<token>.json`)
  - `load_killed_fingerprints(tenant_id) -> set[tuple[str, str]]`
  - `add_killed_fingerprints(tenant_id, keys: Sequence[tuple[str, str]]) -> None`
  - `fingerprint_from_pack(pack) -> tuple[str, str] | None` — `(evidence.fingerprint_kind, evidence.fingerprint_value)` else `("scout_report_id", scout_report_id)`
  - `disable_ai_shadow_packs(helpfulness) -> list[str]` — if not `should_kill` from verdict, return `[]`. Else set every loaded pack with `mode=shadow` and `is_ai_authored=true` to `mode=disabled`, append rule-change `kill_shadow_pack_leftover_fp`, add fingerprints, `load_rules()`. Skip slip (`authored_by=slip_critic` or `is_ai_authored` false).
  - `maybe_kill_leftover_fp_shadows(tenant_id) -> list[str]` — compute leftover helpfulness via `compute_desk_and_leftover_gates` leftover object (or accept leftover_g). Call disable. **Not** called from GET.

- [ ] **Step 1: Tests** (tmp_path rules dir + monkeypatch `settings.rules_path` / y_label dir)

```python
def test_disable_skips_human_and_slip(tmp_path, monkeypatch):
    # write three packs: ai shadow, human shadow, slip shadow
    # leftover helpfulness fp_over_cap
    # assert only ai file mode=disabled; others unchanged
    # load_killed_fingerprints contains the ai fingerprint
    # second call is a no-op (already disabled)
```

- [ ] **Step 2: FAIL** then implement. Use the same path hygiene as `shadow_auto_promote.load_provision` (content-addressed tenant token).

- [ ] **Step 3: GET still does not call this.**

- [ ] **Step 4: Commit** — skip unless asked.

---

### Task 4: Tick hooks + scout-pack refuse + disabled on GET drafts

**Files:**
- Modify: `services/decision-api/src/decision_api/calibration_api.py` (y_label persist tick)
- Modify: `services/decision-api/src/decision_api/rule_api.py` (scout-pack + auto-promote-tick)
- Modify: `services/decision-api/src/decision_api/json_rules.py` if needed — keep a `_disabled_mode_packs` list so GET can show them
- Test: `services/decision-api/tests/test_brain_wire_api.py`

**Interfaces:**
- After `maybe_auto_promote_shadow` / `maybe_park_live_rule_slip`, call `maybe_kill_leftover_fp_shadows` (fail-soft).
- scout-pack POST: if `body.tenant_id` set, compute leftover gate + precision + verdict on `body.rules` ids. If not `publish_allowed` → **409** with `reason`. If `stamp_underpowered`, merge `evidence.leftover_helpfulness = {labeled_extras, extra_tp, extra_fp, hint: helpfulness_underpowered}` before write.
- If fingerprint is in killed set → **409** `leftover_helpfulness_killed`.
- GET `shadow_drafts` includes disabled AI packs: `{name, is_ai_authored, mode}` where mode may be `disabled`.
- Promote of `mode=disabled` stays 404 / not a shadow draft (existing `get_shadow_packs()` excludes them).

- [ ] **Step 1: Tests**
  - GET never creates a disabled file (tmp rules dir unchanged).
  - Tick with fp_over_cap helpfulness (mock leftover compute) disables an ai shadow pack.
  - scout-pack POST with killed fingerprint → 409.
  - scout-pack POST with underpowered helpfulness writes evidence stamp; `mode` stays `shadow`.

- [ ] **Step 2–4:** TDD then wire the three tick sites already used for leftover HIL + slip.

- [ ] **Step 5: Commit** — skip unless asked.

---

### Task 5: Scout publisher reads GET

**Files:**
- Modify: `services/shadow_agent/scout_pack_publisher.py`
- Test: `services/shadow_agent/tests/test_brain_wire_publish.py`

**Interfaces:**
- `async def leftover_gate_payload(tenant_id: str, *, decision_api_url: str | None = None) -> dict | None` — GET `/v1/calibration/shadow-promote-gate?tenant_id=`. Same headers as scout-pack POST (governance secret + actor). Non-2xx / exception → `None`.
- `publish_scout_pack` / burst: tenant from `report.get("tenant_id")` or `scan_payload.get("tenant_id")`. Missing → `{"published": False, "reason": "leftover_helpfulness_no_tenant"}` (do not POST).
- Gate GET `None` → `leftover_helpfulness_unavailable`.
- Call `brain_wire_verdict` from the GET body (`leftover_promote_gate.helpfulness`, `rule_precision_after_labels`, leftover `fp_rate_cap` from helpfulness or 0.4). If not allowed, return that reason; do not POST.
- If `stamp_underpowered`, set `pack["evidence"]["leftover_helpfulness"]` before POST.
- Do not treat leftover cost blockers or `live_rule_slip` as drop.
- Import `brain_wire_verdict` from decision-api **or** duplicate the 40-line function in shadow_agent to avoid a new package dep. Prefer `PYTHONPATH` import `decision_api.brain_wire` if shadow-agent tests already see decision-api; else copy the function into `scout_pack_publisher.py` (ponytail: one copy; upgrade is a shared wheel).

- [ ] **Step 1: Tests** with monkeypatched GET:
  - fp_over_cap → no POST, reason set
  - underpowered → POST happens (mock `_post_pack` / urlopen), evidence stamp
  - missing tenant → no GET, no POST
  - GET 500 → `leftover_helpfulness_unavailable`
  - SLA blocker only → POST allowed

- [ ] **Step 2–4:** TDD then implement.

- [ ] **Step 5: Commit** — skip unless asked.

---

### Task 6: Recommender `dropped` + PACK_AUTHOR 8–9

**Files:**
- Modify: `services/decision-api/src/decision_api/recommend_api.py` (`/analyze`)
- Modify: `services/shadow_agent/PACK_AUTHOR.md`
- Test: `services/decision-api/tests/test_brain_wire_api.py` (analyze) + existing pack-author contract test if one asserts hard-stop list

**Interfaces:**
- After `generate_recommendations`, filter ids with the same rule-FP stop using leftover HIL precision for that tenant (reuse compute / `rule_precision_after_labels` on the analyze records after y_label join if cheap; else GET-equivalent compute). Return `dropped: [{rule_id, reason}]` (`rule_fp_over_cap`). Keep list is the filtered recommendations. Do not write an active pack.
- PACK_AUTHOR add:

```
8. **You must not ignore leftover helpfulness.** If the host injects leftover_helpfulness / per-rule FP and blockers fire, return no pack. You still cannot promote. Optional evidence.proposed_gates is display-only.
9. **You cannot provision auto-promote.** That PUT is human-only.
```

- [ ] **Step 1:** Test analyze with a mocked precision row `fp_rate=0.8` enough_support → that recommendation is in `dropped`, not `recommendations`.
- [ ] **Step 2:** PACK_AUTHOR / contract test still forbids `mode=active` (existing test). Add assert `"leftover helpfulness"` in PACK_AUTHOR.md text.
- [ ] **Step 3–4:** Implement.
- [ ] **Step 5: Commit** — skip unless asked.

---

## Self-review (spec coverage)

| Spec | Task |
|------|------|
| GET helpfulness + precision | 2 |
| Drop FP / no-lift / rule FP / no tenant / GET fail | 1, 5 |
| Underpowered stamp | 1, 4, 5 |
| Cost blockers do not drop publish | 1, 5 |
| Kill AI shadow + durable fingerprint | 3, 4 |
| GET no write | 2, 4 |
| Recommender dropped | 6 |
| PACK_AUTHOR 8–9 | 6 |
| Host auto-promote after publish (already leftover HIL) | out (exists) |
| Live-rule slip rewrite | **out** |
