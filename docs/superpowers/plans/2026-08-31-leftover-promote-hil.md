# Leftover cost + labeled helpfulness on named-draft promote Implementation Plan

> **Shipped on `master` except Task 9 (shadow-first / force-live).** Do not re-execute Tasks 1–8 as greenfield.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a named-draft promote when leftover cost or leftover-extra helpfulness fails, and allow host auto-promote only after the user provisions gates on first review.

**Architecture:** Pure extras + helpfulness from the existing 500-row Observe CC window and `y_label_store`. Leftover list + ack stay on case-api. `desk_promote_gate` requires `leftover_promote_gate`. Desk Promote and `PUT …/mode=active` share the leftover floor. Auto-promote is a decision-api host tick after provision — Scout still writes `mode=shadow` only.

**Tech Stack:** FastAPI case-api + decision-api, SQLAlchemy/alembic, file provision next to `y_label_store`, React `/ops/shadow`, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-08-31-leftover-promote-hil-design.md`

**Not this plan:** [Observe brain wire](../specs/2026-08-31-observe-brain-wire-design.md) (Scout must *read* leftover helpfulness before authoring). Do not start it here.

## Global Constraints

- Decision-api / Rust packs remain sole allow/deny. Evaluate never waits on graph. Leftover list never calls graph.
- Scout / LLM cannot set `mode=active`, call desk Promote, or call force-live. `PACK_AUTHOR.md` hard stops stay.
- API create/update persist `mode=shadow`. Edit of a live pack demotes it. The only paths to `active` are desk Promote, provisioned host auto-promote, or `POST …/force-live` (human actor + reason). After force-live ships, raw `PUT …/mode=active` is `409 shadow_first`.
- Default `auto_promote` is false. Env caps are pre-review defaults; provision wins after first review (`version >= 1`).
- User cannot disable `leftover_queue_unavailable`, `leftover_sla_breached`, leftover helpfulness blockers, or labels/McNemar/drift.
- No auto-ack. `leftover_claimer_ack_required` blocks auto-promote.
- No auto-demote of already-`active` packs when gates tighten.
- Wasm / trend `409 never_auto_promote` is unchanged.
- `/ops/shadow` is always-on lean. `planeForPath("/ops/shadow")` stays null (not `signals`).
- Do not implement brain-wire publish drops or durable scout kill.
- Do not commit unless the user asks (overrides frequent-commit habit).
- CI case-api: `cd services/case-api && PYTHONPATH=src:.:../shared pytest tests/test_leftovers.py -q`
- CI decision-api: `cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_leftover_promote_gate.py tests/test_shadow_promote_gate_api.py tests/test_shadow_auto_promote.py tests/test_shadow_first_writes.py -q`
- CI frontend: `cd frontend && npm test -- --run src/config/leanNav.test.ts`

## File map

| File | Responsibility |
|------|----------------|
| `services/decision-api/src/decision_api/leftover_promote_gate.py` | Extra rows, helpfulness, leftover_promote_gate, leftover list fetch |
| `services/decision-api/tests/test_leftover_promote_gate.py` | Pure + gate compose tests |
| `services/decision-api/src/decision_api/calibration_api.py` | Fold leftover gate into shadow-promote-gate; tick after y_label persist |
| `services/decision-api/src/decision_api/shadow_auto_promote.py` | Provision file + `maybe_auto_promote_shadow` |
| `services/decision-api/src/decision_api/rule_api.py` | Provision HTTP, desk Promote, mode=active leftover floor, tick, scout-pack hook, shadow-first writes, force-live |
| `services/decision-api/tests/test_shadow_auto_promote.py` | Provision, Promote 409/200, tick, mode=active leftover |
| `services/decision-api/tests/test_shadow_promote_gate_api.py` | `leftover_promote_gate` on GET |
| `services/case-api/src/case_api/models.py` | `LeftoverPromoteAck` |
| `services/case-api/alembic/versions/20260831_011_leftover_promote_ack.py` | Postgres table |
| `services/case-api/src/case_api/main.py` | `GET/POST /v1/leftovers/promote-ack` **before** `/{case_id}` |
| `services/case-api/tests/test_leftovers.py` | Ack 200/403/stale |
| `frontend/src/config/leanNav.ts` | `/ops/shadow` in `LEAN_NAV_PATHS` |
| `frontend/src/pages/OpsShadow.tsx` | Leftover card + provision + Promote |
| `frontend/src/api/client.ts` | leftover gate types, provision, promote, ack |

---

### Task 1: Extra rows + leftover mint count + helpfulness

**Files:**
- Create: `services/decision-api/src/decision_api/leftover_promote_gate.py`
- Create: `services/decision-api/tests/test_leftover_promote_gate.py`

**Interfaces:**
- Consumes: CC row shape `{trace_id, entity_id, champion_decision, challenger_decision}` (same as `aggregate_champion_challenger` audit rows)
- Produces:
  - `MINTING = frozenset({"deny", "review"})`
  - `extra_review_or_deny_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]`
  - `extra_leftover_mint_count(extras: Sequence[Mapping[str, Any]], *, mint_on: bool) -> int`
  - `leftover_helpfulness(extras, *, by_trace: Mapping[str, str], by_entity: Mapping[str, str], min_labeled_extras: int = 5, fp_rate_cap: float = 0.4) -> dict[str, Any]`

- [ ] **Step 1: Write the failing tests**

```python
# services/decision-api/tests/test_leftover_promote_gate.py
from decision_api.leftover_promote_gate import (
    extra_leftover_mint_count,
    extra_review_or_deny_rows,
    leftover_helpfulness,
    leftover_promote_gate,
)


def test_allow_to_review_is_extra_deny_to_review_is_not():
    rows = [
        {"trace_id": "t1", "entity_id": "e1", "champion_decision": "allow", "challenger_decision": "review"},
        {"trace_id": "t2", "entity_id": "e2", "champion_decision": "deny", "challenger_decision": "review"},
        {"trace_id": "t3", "entity_id": "e3", "champion_decision": "flag", "challenger_decision": "deny"},
    ]
    extras = extra_review_or_deny_rows(rows)
    assert {r["trace_id"] for r in extras} == {"t1", "t3"}
    assert extra_leftover_mint_count(extras, mint_on=True) == 2
    assert extra_leftover_mint_count(extras, mint_on=False) == 0


def test_helpfulness_fp_over_cap_and_underpowered():
    extras = [
        {"trace_id": f"t{i}", "entity_id": f"e{i}", "champion_decision": "allow", "challenger_decision": "review"}
        for i in range(5)
    ]
    by_trace = {f"t{i}": "0" for i in range(5)}
    h = leftover_helpfulness(extras, by_trace=by_trace, by_entity={}, min_labeled_extras=5, fp_rate_cap=0.4)
    assert h["labeled_extras"] == 5
    assert h["extra_fp"] == 5
    assert h["extra_tp"] == 0
    assert h["fp_rate"] == 1.0
    assert h["underpowered"] is False
    assert "leftover_extras_fp_over_cap" in h["blockers"]
    assert "leftover_extras_no_lift" in h["blockers"]

    h2 = leftover_helpfulness(extras[:3], by_trace={"t0": "0", "t1": "0", "t2": "0"}, by_entity={})
    assert h2["underpowered"] is True
    assert h2["blockers"] == []


def test_helpfulness_tp_does_not_block_and_proxy_ignored():
    extras = [
        {"trace_id": f"t{i}", "entity_id": f"e{i}", "champion_decision": "allow", "challenger_decision": "review"}
        for i in range(5)
    ]
    by_trace = {f"t{i}": "1" for i in range(5)}
    h = leftover_helpfulness(extras, by_trace=by_trace, by_entity={})
    assert h["extra_tp"] == 5
    assert h["blockers"] == []
    h3 = leftover_helpfulness(extras, by_trace={"t0": "proxy"}, by_entity={})
    assert h3["labeled_extras"] == 0
    assert h3["underpowered"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_leftover_promote_gate.py::test_allow_to_review_is_extra_deny_to_review_is_not -q`

Expected: FAIL import `leftover_promote_gate`

- [ ] **Step 3: Write minimal implementation**

```python
# services/decision-api/src/decision_api/leftover_promote_gate.py
from __future__ import annotations

from typing import Any, Mapping, Sequence

MINTING = frozenset({"deny", "review"})


def extra_review_or_deny_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        champ = str(row.get("champion_decision") or "").strip().lower()
        chall = str(row.get("challenger_decision") or "").strip().lower()
        if champ and chall and champ not in MINTING and chall in MINTING:
            out.append(dict(row))
    return out


def extra_leftover_mint_count(extras: Sequence[Mapping[str, Any]], *, mint_on: bool) -> int:
    return len(extras) if mint_on else 0


def leftover_helpfulness(
    extras: Sequence[Mapping[str, Any]],
    *,
    by_trace: Mapping[str, str],
    by_entity: Mapping[str, str],
    min_labeled_extras: int = 5,
    fp_rate_cap: float = 0.4,
) -> dict[str, Any]:
    extra_tp = 0
    extra_fp = 0
    labeled = 0
    for row in extras:
        tid = str(row.get("trace_id") or "").strip()
        eid = str(row.get("entity_id") or "").strip()
        lab = by_trace.get(tid) if tid else None
        if lab is None and eid:
            lab = by_entity.get(eid)
        if lab not in {"0", "1"}:
            continue
        labeled += 1
        if lab == "1":
            extra_tp += 1
        else:
            extra_fp += 1
    fp_rate = (extra_fp / labeled) if labeled else None
    underpowered = labeled < min_labeled_extras
    blockers: list[str] = []
    if not underpowered and fp_rate is not None and fp_rate > fp_rate_cap:
        blockers.append("leftover_extras_fp_over_cap")
    if not underpowered and extra_tp == 0 and extra_fp >= min_labeled_extras:
        blockers.append("leftover_extras_no_lift")
    return {
        "labeled_extras": labeled,
        "extra_tp": extra_tp,
        "extra_fp": extra_fp,
        "fp_rate": round(fp_rate, 4) if fp_rate is not None else None,
        "fp_rate_cap": fp_rate_cap,
        "min_labeled_extras": min_labeled_extras,
        "underpowered": underpowered,
        "blockers": blockers,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_leftover_promote_gate.py -q -k "extra or helpfulness"`

Expected: PASS (gate compose tests from Task 2 may still fail if already added)

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 2: leftover_promote_gate composer

**Files:**
- Modify: `services/decision-api/src/decision_api/leftover_promote_gate.py`
- Modify: `services/decision-api/tests/test_leftover_promote_gate.py`

**Interfaces:**
- Consumes: Task 1 helpers
- Produces:
  - `ack_is_valid(ack: Mapping[str, Any] | None, claimers: Sequence[str]) -> bool`
  - `leftover_promote_gate(*, leftovers: list[dict[str, Any]] | None, extras: Sequence[Mapping[str, Any]], mint_on: bool, add_cap: int, helpfulness: Mapping[str, Any], ack: Mapping[str, Any] | None, draft_id: str | None) -> dict[str, Any]`
  - leftovers `None` = unavailable. Each leftover dict uses list-API keys: `sla_breached`, `claimed_by`.

- [ ] **Step 1: Write the failing tests** (append to `test_leftover_promote_gate.py`)

```python
def test_gate_fail_closed_when_leftovers_unavailable():
    g = leftover_promote_gate(
        leftovers=None,
        extras=[],
        mint_on=False,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack=None,
        draft_id="d1",
    )
    assert g["promote_allowed"] is False
    assert "leftover_queue_unavailable" in g["blockers"]


def test_gate_sla_volume_ack_and_empty_green():
    sla = [{"sla_breached": True, "claimed_by": None}]
    g = leftover_promote_gate(
        leftovers=sla,
        extras=[],
        mint_on=True,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack=None,
        draft_id="d1",
    )
    assert "leftover_sla_breached" in g["blockers"]

    extras = [{"trace_id": f"t{i}", "champion_decision": "allow", "challenger_decision": "review"} for i in range(11)]
    g2 = leftover_promote_gate(
        leftovers=[],
        extras=extras,
        mint_on=True,
        add_cap=10,
        helpfulness=leftover_helpfulness(extras, by_trace={}, by_entity={}),
        ack=None,
        draft_id="d1",
    )
    assert "leftover_add_over_cap" in g2["blockers"]
    assert g2["extra_leftover_mint"] == 11

    claimed = [{"sla_breached": False, "claimed_by": "ana-a"}]
    g3 = leftover_promote_gate(
        leftovers=claimed,
        extras=[],
        mint_on=False,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack=None,
        draft_id="d1",
    )
    assert "leftover_claimer_ack_required" in g3["blockers"]
    g4 = leftover_promote_gate(
        leftovers=claimed,
        extras=[],
        mint_on=False,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack={"draft_id": "d1", "acked_by": "ana-a", "acked_at": "t"},
        draft_id="d1",
    )
    assert g4["promote_allowed"] is True

    g5 = leftover_promote_gate(
        leftovers=[],
        extras=[],
        mint_on=False,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack=None,
        draft_id=None,
    )
    assert g5["promote_allowed"] is True
    assert g5["ack_required"] is False
```

- [ ] **Step 2: Run the new tests — expect FAIL** (`leftover_promote_gate` missing)

- [ ] **Step 3: Implement composer**

```python
def ack_is_valid(ack: Mapping[str, Any] | None, claimers: Sequence[str]) -> bool:
    if not ack:
        return False
    who = str(ack.get("acked_by") or "").strip()
    return bool(who) and who in {str(c).strip() for c in claimers if str(c).strip()}


def leftover_promote_gate(
    *,
    leftovers: list[dict[str, Any]] | None,
    extras: Sequence[Mapping[str, Any]],
    mint_on: bool,
    add_cap: int,
    helpfulness: Mapping[str, Any],
    ack: Mapping[str, Any] | None,
    draft_id: str | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    leftover_count = 0
    sla_n = 0
    claimers: list[str] = []
    if leftovers is None:
        blockers.append("leftover_queue_unavailable")
    else:
        leftover_count = len(leftovers)
        for row in leftovers:
            if row.get("sla_breached"):
                sla_n += 1
            who = str(row.get("claimed_by") or "").strip()
            if who and who not in claimers:
                claimers.append(who)
        if sla_n:
            blockers.append("leftover_sla_breached")
    mint_n = extra_leftover_mint_count(extras, mint_on=mint_on)
    if mint_n > add_cap:
        blockers.append("leftover_add_over_cap")
    ack_required = bool(claimers)
    if ack_required and not ack_is_valid(ack, claimers):
        blockers.append("leftover_claimer_ack_required")
    for b in helpfulness.get("blockers") or []:
        if b not in blockers:
            blockers.append(str(b))
    hint = "queue_empty"
    if leftovers is None:
        hint = "leftover_queue_unavailable"
    elif helpfulness.get("underpowered") and extras:
        hint = "helpfulness_underpowered"
    elif not extras:
        hint = "no_observe_pairs"
    elif not mint_on:
        hint = "mint_off_extras_are_display_only"
    return {
        "schema_id": "tarka.leftover_promote_gate/v1",
        "promote_allowed": len(blockers) == 0,
        "blockers": blockers,
        "extra_review_or_deny": len(extras),
        "extra_leftover_mint": mint_n,
        "leftover_mint_on": bool(mint_on),
        "cap": add_cap,
        "sla_breached_count": sla_n,
        "leftover_count": leftover_count,
        "claimers": claimers,
        "ack_required": ack_required,
        "ack": dict(ack) if ack else None,
        "helpfulness": dict(helpfulness),
        "hint": hint,
        "draft_id": draft_id,
    }
```

- [ ] **Step 4: Run** `pytest tests/test_leftover_promote_gate.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 3: Case-api leftover promote ack

**Files:**
- Modify: `services/case-api/src/case_api/models.py`
- Create: `services/case-api/alembic/versions/20260831_011_leftover_promote_ack.py`
- Modify: `services/case-api/src/case_api/main.py` (register `promote-ack` **above** `/{case_id}/claim`)
- Modify: `services/case-api/tests/test_leftovers.py`

**Interfaces:**
- Consumes: `actor_from_request` / `_actor_id`, leftover list `claimed_by`
- Produces: table `leftover_promote_acks` unique `(tenant_id, draft_id)`; `POST/GET /v1/leftovers/promote-ack`

- [ ] **Step 1: Write the failing HTTP tests** (append to `test_leftovers.py`)

```python
def test_promote_ack_403_unless_claimer_and_stale_after_release(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    a = {**_api_headers(), "X-Actor-Id": "ana-a"}
    b = {**_api_headers(), "X-Actor-Id": "ana-b"}
    case_client.post(
        "/v1/entities/buyer-ack/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=a,
    )
    denied = case_client.post(
        "/v1/leftovers/promote-ack",
        json={"tenant_id": "demo", "draft_id": "scout_x"},
        headers=b,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "not_a_claimer"
    ok = case_client.post(
        "/v1/leftovers/promote-ack",
        json={"tenant_id": "demo", "draft_id": "scout_x"},
        headers=a,
    )
    assert ok.status_code == 200, ok.text
    got = case_client.get(
        "/v1/leftovers/promote-ack",
        params={"tenant_id": "demo", "draft_id": "scout_x"},
        headers=_api_headers(),
    )
    assert got.status_code == 200
    body = got.json()
    assert body["required"] is True
    assert body["ack"]["acked_by"] == "ana-a"
    case_client.post(
        "/v1/entities/buyer-ack/act",
        json={"tenant_id": "demo", "action": "release"},
        headers=a,
    )
    after = case_client.get(
        "/v1/leftovers/promote-ack",
        params={"tenant_id": "demo", "draft_id": "scout_x"},
        headers=_api_headers(),
    )
    assert after.json()["required"] is False
```

- [ ] **Step 2: Run** `pytest tests/test_leftovers.py::test_promote_ack_403_unless_claimer_and_stale_after_release -q` — expect FAIL 404

- [ ] **Step 3: Model + alembic + routes**

Add to `models.py`:

```python
class LeftoverPromoteAck(Base):
    __tablename__ = "leftover_promote_acks"
    __table_args__ = (UniqueConstraint("tenant_id", "draft_id", name="uq_leftover_promote_acks_tenant_draft"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    draft_id: Mapped[str] = mapped_column(String(256))
    acked_by: Mapped[str] = mapped_column(String(256))
    acked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Alembic `20260831_011` revises `20260831_010`. `CREATE TABLE IF NOT EXISTS leftover_promote_acks` with unique `(tenant_id, draft_id)`. Mirror `010` inspector style if you prefer add-if-missing.

In `main.py`, **before** `@app.post("/v1/leftovers/{case_id}/claim")`:

```python
class LeftoverPromoteAckIn(BaseModel):
    tenant_id: str
    draft_id: str


@app.get("/v1/leftovers/promote-ack")
async def get_leftover_promote_ack(tenant_id: str, draft_id: str, session: AsyncSession = Depends(get_session), _=Depends(require_role_or_insecure_desk("analyst"))):
    # load leftovers for tenant; claimers = unique claimed_by; required = bool(claimers)
    # ack row for (tenant_id, draft_id) or None
    ...


@app.post("/v1/leftovers/promote-ack")
async def post_leftover_promote_ack(body: LeftoverPromoteAckIn, request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_role_or_insecure_desk("analyst"))):
    # draft_id blank → 400
    # actor not in claimers → 403 {"detail": "not_a_claimer"}
    # upsert ack; 200 {ack, claimers, required: true}
```

GET `required` = at least one leftover claimed (spec), even if ack row still exists after release.

- [ ] **Step 4: Run** `pytest tests/test_leftovers.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 4: Fetch leftovers + fold into shadow-promote-gate

**Files:**
- Modify: `services/decision-api/src/decision_api/leftover_promote_gate.py` (`async def fetch_leftover_list`, `async def fetch_promote_ack`)
- Modify: `services/decision-api/src/decision_api/calibration_api.py` (`shadow_promote_gate`)
- Modify: `services/decision-api/tests/test_shadow_promote_gate_api.py`

**Interfaces:**
- Consumes: `settings.case_api_url`, `settings.case_internal_token`, `settings.case_create_on_deny_review`, `load_y_labels`, `aggregate_champion_challenger` rows, provision caps (Task 5 — until then use env defaults)
- Produces: GET body includes `leftover_promote_gate`; `desk_promote_gate.requires` includes `"leftover_promote_gate"`; `desk_promote_gate.promote_allowed` is false if leftover blockers exist
- Optional query `draft_id` on shadow-promote-gate for ack lookup

- [ ] **Step 1: Extend `test_shadow_promote_gate_api.py`**

```python
@pytest.mark.asyncio
async def test_shadow_promote_gate_includes_leftover_gate(challenge_client, monkeypatch):
    monkeypatch.setattr("decision_api.config.settings.case_api_url", "")
    r = await challenge_client.get("/v1/calibration/shadow-promote-gate")
    assert r.status_code == 200
    body = r.json()
    assert body["leftover_promote_gate"]["schema_id"] == "tarka.leftover_promote_gate/v1"
    assert "leftover_queue_unavailable" in body["leftover_promote_gate"]["blockers"]
    assert "leftover_promote_gate" in body["desk_promote_gate"]["requires"]
    assert body["desk_promote_gate"]["promote_allowed"] is False
```

- [ ] **Step 2: Run — expect FAIL** missing key `leftover_promote_gate`

- [ ] **Step 3: Fetch + fold**

```python
# leftover_promote_gate.py
import httpx
from decision_api.config import settings

async def fetch_leftover_list(tenant_id: str) -> list[dict[str, Any]] | None:
    base = (settings.case_api_url or "").strip().rstrip("/")
    if not base or not (tenant_id or "").strip():
        return None
    headers = {}
    tok = (settings.case_internal_token or "").strip()
    if tok:
        headers["X-Internal-Token"] = tok
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/v1/leftovers", params={"tenant_id": tenant_id}, headers=headers)
        if r.status_code >= 400:
            return None
        rows = r.json().get("leftovers")
        return rows if isinstance(rows, list) else None
    except Exception:
        return None


async def fetch_promote_ack(tenant_id: str, draft_id: str) -> dict[str, Any] | None:
    # same base/headers; GET /v1/leftovers/promote-ack; return json["ack"]
    ...
```

In `shadow_promote_gate`:
1. Build extras from `cc_audit["audit_rows"]` (ensure aggregate returns them — it already has `audit_rows` in the existing function; use those).
2. `load_y_labels(tid)` when tid else empty maps.
3. Caps: `int(os.environ.get("LEFTOVER_PROMOTE_ADD_CAP", "10"))` until Task 5 reads provision.
4. `leftover_g = leftover_promote_gate(...)`
5. Append leftover blockers onto `desk_promote` blockers; add `"leftover_promote_gate"` to `requires`.
6. Return `leftover_promote_gate` on the body.
7. Also return `shadow_drafts: [{"name": str, "is_ai_authored": bool, "mode": "shadow"}]` from `get_shadow_packs()` so the desk picker does not need a second list API.

Accept optional `draft_id: str | None = Query(None)`.

- [ ] **Step 4: Run** `pytest tests/test_shadow_promote_gate_api.py tests/test_leftover_promote_gate.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 5: Shadow auto-promote provision (file + HTTP)

**Files:**
- Create: `services/decision-api/src/decision_api/shadow_auto_promote.py`
- Create: `services/decision-api/tests/test_shadow_auto_promote.py`
- Modify: `services/decision-api/src/decision_api/rule_api.py`
- Modify: `services/decision-api/src/decision_api/leftover_promote_gate.py` or calibration to call `load_provision(tenant_id)` for caps when `version >= 1`

**Interfaces:**
- Consumes: `y_label_store._data_dir` / `_file_token` pattern (do not put raw tenant in the filename)
- Produces:
  - `SCHEMA = "tarka.shadow_auto_promote_provision/v1"`
  - `default_provision(tenant_id: str) -> dict` (`auto_promote=False`, caps 10 / 0.4 / 5, `version=0`)
  - `load_provision(tenant_id: str) -> dict`
  - `save_provision(tenant_id: str, *, auto_promote: bool, leftover_add_cap: int, leftover_fp_rate_cap: float, min_labeled_extras: int, provisioned_by: str) -> dict` (increments version)
  - `GET/PUT /v1/rules/shadow-auto-promote-provision`

- [ ] **Step 1: Failing tests** (pure first)

```python
def test_provision_default_then_save_increments(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    from decision_api.shadow_auto_promote import default_provision, load_provision, save_provision

    d = default_provision("t1")
    assert d["auto_promote"] is False
    assert d["version"] == 0
    assert load_provision("t1")["version"] == 0
    s = save_provision(
        "t1",
        auto_promote=True,
        leftover_add_cap=3,
        leftover_fp_rate_cap=0.2,
        min_labeled_extras=6,
        provisioned_by="ops",
    )
    assert s["version"] == 1
    assert s["auto_promote"] is True
    assert s["leftover_add_cap"] == 3
    assert load_provision("t1")["version"] == 1
    s2 = save_provision(
        "t1",
        auto_promote=True,
        leftover_add_cap=0,
        leftover_fp_rate_cap=0.2,
        min_labeled_extras=6,
        provisioned_by="ops",
    )
    assert s2["version"] == 2
    assert s2["leftover_add_cap"] == 0
```

Validate: `leftover_add_cap >= 0`, `0 <= leftover_fp_rate_cap <= 1`, `min_labeled_extras >= 1`. Raise `ValueError` otherwise.

- [ ] **Step 2: Run — expect FAIL** import

- [ ] **Step 3: File store** (copy `_file_token` + `_data_dir` from `y_label_store`; filename `shadow_auto_promote_{token}.json`)

Wire GET/PUT on `rule_api` with `require_role("analyst")`. PUT body fields only; server sets `provisioned_by` from `X-Actor` / user id, `provisioned_at` ISO UTC.

In `shadow_promote_gate`, if `load_provision(tid)["version"] >= 1` use provision caps, else env defaults.

- [ ] **Step 4: Run** `pytest tests/test_shadow_auto_promote.py -q` — expected PASS for provision tests

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 6: Desk Promote, mode=active leftover floor, auto-promote tick

**Files:**
- Modify: `services/decision-api/src/decision_api/shadow_auto_promote.py` (`maybe_auto_promote_shadow`, `activate_shadow_pack`)
- Modify: `services/decision-api/src/decision_api/rule_api.py`
- Modify: `services/decision-api/tests/test_shadow_auto_promote.py`

**Interfaces:**
- Consumes: `get_shadow_packs()`, leftover_promote_gate + desk science (extract a shared `compute_desk_and_leftover_gates(tenant_id, draft_id)` used by calibration GET, Promote, tick, and `set_pack_mode`)
- Produces:
  - `POST /v1/rules/shadow-packs/{draft_id}/promote?tenant_id=` → 200 or 409 `{detail: "promote_blocked", desk_promote_gate, leftover_promote_gate}`
  - `POST /v1/rules/shadow-packs/auto-promote-tick?tenant_id=`
  - `set_pack_mode(mode=active)` runs leftover_promote_gate (query `tenant_id`); leftover blockers → 409
  - `maybe_auto_promote_shadow(tenant_id: str) -> dict` — no-op if `not provision.auto_promote`; no auto-ack; only `is_ai_authored` shadow packs

Register `/shadow-packs/auto-promote-tick` and `/shadow-auto-promote-provision` **before** `/{filename}/mode`.

- [ ] **Step 1: Tests** (tmp rules dir + monkeypatch leftover fetch to `[]`)

```python
@pytest.mark.asyncio
async def test_promote_409_when_leftover_blocked_200_when_green(tmp_path, monkeypatch):
    # write a shadow is_ai_authored pack; monkeypatch leftover_promote_gate leftovers=[]
    # monkeypatch desk science blockers to [] for the green case
    ...


@pytest.mark.asyncio
async def test_tick_noop_without_provision(tmp_path, monkeypatch):
    ...


@pytest.mark.asyncio
async def test_tick_promotes_ai_shadow_when_provisioned_and_green(tmp_path, monkeypatch):
    ...


@pytest.mark.asyncio
async def test_set_mode_active_409_on_sla(tmp_path, monkeypatch):
    # leftovers=[{sla_breached: True}]; PUT mode=active with governance secret + tenant_id
    ...
```

Reuse the calibration test app pattern (`ALLOW_INSECURE_NO_AUTH`, inject analyst). For `set_pack_mode` also set `RULE_GOVERNANCE_SECRET` if `_require_rule_governance` needs it — read `_require_rule_governance` and match existing rule_api tests.

- [ ] **Step 2: Run — expect FAIL** 404 on new routes

- [ ] **Step 3: Implement**

`activate_shadow_pack(draft_id: str, *, actor: str, reason: str) -> dict`: resolve first `get_shadow_packs()` name match; set `mode=active`; write file (`_source_file` / `_file`); `load_rules()`; `_append_rule_change`.

`maybe_auto_promote_shadow`: load provision; if not `auto_promote` return `{auto_promote: False, promoted: [], reason: "not_provisioned"}`; compute gates; if leftover or desk blocked return reason + gates; else activate each `is_ai_authored` shadow pack.

Desk Promote: `require_role("analyst")` (no governance secret). 404 `no_shadow_draft` if name missing.

`set_pack_mode` when `body.mode == "active"`: compute leftover gate with query `tenant_id`; if leftover blockers, 409 (do **not** require McNemar on this path).

GET shadow-promote-gate must **not** call `maybe_auto_promote_shadow`.

- [ ] **Step 4: Run** `pytest tests/test_shadow_auto_promote.py tests/test_shadow_promote_gate_api.py tests/test_leftover_promote_gate.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 7: Auto-promote triggers (scout-pack + y_label persist)

**Files:**
- Modify: `services/decision-api/src/decision_api/rule_api.py` (`create_scout_pack`)
- Modify: `services/decision-api/src/decision_api/calibration_api.py` (after `merge_y_labels` when `persist_incoming`)
- Modify: `services/decision-api/tests/test_shadow_auto_promote.py`

**Interfaces:**
- Consumes: `maybe_auto_promote_shadow(tenant_id)`
- Produces: after successful scout-pack write, if request/body has `tenant_id` (add optional `tenant_id` on `ScoutPackIn`, default `""`) call tick; after y_label persist in reliability merge, call tick. Failures in tick are logged, not raised (promote path is fail-closed on *gates*, not on tick exceptions — still log). Scout response `mode` stays `"shadow"`; file may already be `active` if tick ran.

- [ ] **Step 1: Test** — provision on + green leftover mock; `create_scout_pack` then `get_shadow_packs()` empty / pack file `mode=active`. Second test: GET shadow-promote-gate does not change pack mode.

- [ ] **Step 2: Run — expect FAIL** pack still shadow

- [ ] **Step 3: Call `maybe_auto_promote_shadow` in those two places only**

- [ ] **Step 4: Run** `pytest tests/test_shadow_auto_promote.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 8: Lean `/ops/shadow` + leftover card

**Files:**
- Modify: `frontend/src/config/leanNav.ts`
- Modify: `frontend/src/config/leanNav.test.ts`
- Modify: `frontend/src/api/client.ts` (`shadowPromoteGate` leftover types; `leftoverPromoteAck`, `shadowAutoPromoteProvision`, `promoteShadowPack`)
- Modify: `frontend/src/pages/OpsShadow.tsx`

**Interfaces:**
- Consumes: leftover HIL APIs
- Produces: `/ops/shadow` in `LEAN_NAV_PATHS`; `planeForPath` unchanged (null); leftover card + provision form + Promote

- [ ] **Step 1: Flip leanNav tests**

In `keeps desk core paths…`:
- `isProductionSurfacePath("/ops/shadow")` → `true`
- `LEAN_NAV_PATHS.has("/ops/shadow")` → `true`
- keep `isProductionSurfacePath("/shadow")` false and `LEAN_NAV_PATHS.has("/shadow")` false

Add: empty `VITE_SIGNAL_API_URL` still shows `/ops/shadow` via `isNavItemVisible("/ops/shadow") === true`.

- [ ] **Step 2: Run** `cd frontend && npm test -- --run src/config/leanNav.test.ts` — expect FAIL

- [ ] **Step 3: Add `"/ops/shadow"` to `LEAN_NAV_PATHS` only.** Do not add it to `EXACT_PATH_PLANE`.

Client: extend `shadowPromoteGate` with `leftover_promote_gate` + `desk_promote_gate.requires`. Add:

```ts
leftoverPromoteAckGet(tenantId: string, draftId: string)
leftoverPromoteAckPost(tenantId: string, draftId: string)
getShadowAutoPromoteProvision(tenantId: string)
putShadowAutoPromoteProvision(body: { tenant_id: string; auto_promote: boolean; leftover_add_cap: number; leftover_fp_rate_cap: number; min_labeled_extras: number })
promoteShadowPack(draftId: string, tenantId: string)
```

`OpsShadow.tsx`: card above science — extras, SLA count, claimers, helpfulness (`underpowered` or `extra_tp`/`extra_fp`/`fp_rate`), draft `<select>` from `GET` leftover gate / a thin `shadow` names list (if no list API, parse `leftover_promote_gate.draft_id` plus `governance_summary` if already on the page; otherwise add `shadow_drafts: [{name}]` to shadow-promote-gate in Task 4 — do that if missing). Ack button (disabled when this actor is not in `claimers`). Provision: three numbers + `auto_promote` checkbox + version/by. Promote button disabled when `!desk_promote_gate.promote_allowed`. Do not remove L3.

- [ ] **Step 4: Run** `npm test -- --run src/config/leanNav.test.ts` — expected PASS

If the frontend has a running desk, click `/ops/shadow` with empty signal URL and confirm the leftover card (not “plane off”).

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 9: Shadow-first writes + force-live

**Files:**
- Modify: `services/decision-api/src/decision_api/rule_api.py`
- Create: `services/decision-api/tests/test_shadow_first_writes.py`
- Modify: `frontend/src/pages/OpsShadow.tsx` (Override control + reason; last `rule_force_live`)
- Modify: `frontend/src/api/client.ts`

**Constraint:** After this task, `PUT …/mode=active` is **409** `shadow_first`. Desk Promote and `maybe_auto_promote_shadow` keep writing `active` via a shared internal helper, not via that PUT. Force-live is the only leftover/science skip.

Register `POST /{filename}/force-live` **before** `/{filename}`.

- [ ] **Step 1: Tests** — expect FAIL

```python
@pytest.mark.asyncio
async def test_create_and_update_persist_shadow(tmp_path, monkeypatch):
    # POST /v1/rules with no mode → file has mode=shadow
    # PUT same file after flipping disk to active → mode=shadow again


@pytest.mark.asyncio
async def test_force_live_requires_actor_and_reason(tmp_path):
    # missing X-Actor or short reason → 403/422
    # actor + reason → 200, mode=active, rule_force_live row


@pytest.mark.asyncio
async def test_put_mode_active_is_shadow_first(tmp_path):
    # PUT …/mode=active → 409 shadow_first even when leftover gate is green
```

- [ ] **Step 2: Implement** — `create_rule_pack` / `update_rule_pack` / add-rule set `mode=shadow`. `POST …/force-live` as spec. `set_pack_mode(active)` → 409 `shadow_first`. Scout / assist caller 403 on force-live.

- [ ] **Step 3: Run** `pytest tests/test_shadow_first_writes.py -q` — expected PASS

- [ ] **Step 4: Commit** — skip unless the user asked.

---

## Self-review (spec coverage)

| Spec requirement | Task |
|------------------|------|
| Extra counts from CC, mint off ⇒ mint extras 0 | 1 |
| Helpfulness y_label 0/1, proxy ignored, underpowered no block, FP/no-lift | 1–2 |
| Queue unavailable / SLA / volume cap / ack-if-claimed | 2–4 |
| Ack 403 / upsert / stale after release | 3 |
| Fold into `desk_promote_gate` | 4 |
| Provision first review / redefine / env defaults | 5 |
| Desk Promote + leftover floor on `PUT mode=active` | 6 |
| Auto-promote host tick; no GET side effect; no auto-ack | 6–7 |
| Scout write stays shadow; host may activate | 7 |
| Lean `/ops/shadow` not signals | 8 |
| Create/update persist `mode=shadow`; edit demotes live | 9 |
| Force-live human-only + `rule_force_live`; PUT mode=active `shadow_first` | 9 |
| Brain wire publish drops / durable kill | **out** (next plan) |
| Wasm never_auto_promote | **untouched** |
