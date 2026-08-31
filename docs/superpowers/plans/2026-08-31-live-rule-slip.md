# Live-rule slip Implementation Plan

> **Shipped on `master` (2026-08-31).** Do not re-execute as greenfield. Historical TDD record.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ping a live `rule_id` on Observe when fire-rate or hit-mix shifts, and park a host shadow pack only when exactly one of H1 (retire) or H2 (successor) has support.

**Architecture:** Pure slip math on the same newest-500 audit + `y_label` as leftover HIL. `GET shadow-promote-gate` returns `live_rule_slip` with no writes. `maybe_park_live_rule_slip` runs on the leftover-HIL tick / y_label merge / scout-pack host side. Slip drafts are `is_ai_authored=false` so auto-promote and brain-wire kill ignore them. Promote does not strip the live rule.

**Tech Stack:** decision-api FastAPI, existing `y_label_store` + `rule_precision_after_labels`, JSON packs on `settings.rules_path`, React `/ops/shadow`, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-08-31-live-rule-slip-design.md`

**Not this plan:** Observe brain wire publish drops. `replaces_rule_id` on Promote. Shadow-first / force-live (leftover HIL Task 9). Hunt / leftovers UI.

## Global Constraints

- Rust packs remain sole allow/deny. Evaluate never waits on graph.
- GET `/v1/calibration/shadow-promote-gate` must not call `maybe_park_live_rule_slip` or write pack files.
- Park only on H1 xor H2. Both thin → `underpowered`. Both true → `ambiguous`. No file in either case.
- Slip packs: `mode=shadow`, `authored_by=slip_critic`, `is_ai_authored=false`. One slot per `evidence.live_rule_id`.
- `maybe_auto_promote_shadow` stays `is_ai_authored` only. Do not activate slip files.
- Scout-pack that would clobber a slip draft → 409 `slip_draft_exists`.
- Promote of a slip draft does not remove the live `rule_id` from another pack.
- `miss_is_not_recall` is always true on ping rows.
- Do not commit unless the user asks.
- CI decision-api: `cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_live_rule_slip.py tests/test_live_rule_slip_api.py tests/test_shadow_promote_gate_api.py -q`
- CI frontend: `cd frontend && npm test -- --run src/domain/liveRuleSlip.test.ts`

## File map

| File | Responsibility |
|------|----------------|
| `services/decision-api/src/decision_api/live_rule_slip.py` | Window, triggers, H1/H2, GET payload, park helpers, `maybe_park_live_rule_slip` |
| `services/decision-api/tests/test_live_rule_slip.py` | Pure math + pack shape |
| `services/decision-api/src/decision_api/leftover_promote_gate.py` | Fold `live_rule_slip` into `compute_desk_and_leftover_gates` |
| `services/decision-api/src/decision_api/calibration_api.py` | Return `live_rule_slip` on GET; tick park after auto-promote |
| `services/decision-api/src/decision_api/rule_api.py` | Tick + scout-pack park hook; scout 409 |
| `services/decision-api/tests/test_live_rule_slip_api.py` | GET no-write, tick park, scout 409, promote does not strip |
| `frontend/src/domain/liveRuleSlip.ts` | One-line desk copy |
| `frontend/src/domain/liveRuleSlip.test.ts` | Copy cases |
| `frontend/src/api/client.ts` | `LiveRuleSlip` on `shadowPromoteGate` |
| `frontend/src/pages/OpsShadow.tsx` | Card under leftover helpfulness |

---

### Task 1: Pure window + triggers + xor hypotheses

**Files:**
- Create: `services/decision-api/src/decision_api/live_rule_slip.py`
- Test: `services/decision-api/tests/test_live_rule_slip.py`

**Interfaces:**
- Consumes: `rule_precision_after_labels(rows, min_labeled_hits=5)` — rows need `y_label`, `rule_hits`, `decision`
- Produces:
  - `resolve_y(row, by_trace, by_entity) -> str | None`
  - `mix_value(row, field: str) -> str`
  - `split_window(rows) -> tuple[list, list, str]`  # current, prior, `"ok"` \| `"underpowered"`
  - `live_rule_slip(rows, *, by_trace, by_entity, fp_cap: float, parked: Sequence[Mapping] = ()) -> dict`

- [ ] **Step 1: Failing tests**

```python
from decision_api.live_rule_slip import live_rule_slip, mix_value, resolve_y, split_window


def _row(i, *, hits=(), y=None, event="payment", geo="US", decision="allow", entity=None):
    return {
        "trace_id": f"t{i}",
        "entity_id": entity or f"e{i}",
        "event_type": event,
        "decision": decision,
        "rule_hits": list(hits),
        "payload_snapshot": {"payload": {"geo_country": geo}},
        "y_label": y or "",
    }


def _half(start, n, **kw):
    return [_row(start + i, **kw) for i in range(n)]


def test_window_underpowered_no_rules():
    rows = _half(0, 40) + _half(40, 40)
    out = live_rule_slip(rows, by_trace={}, by_entity={}, fp_cap=0.4)
    assert out["window"] == "underpowered"
    assert out["rules"] == []


def test_fire_rate_only_underpowered_hypothesis():
    prior = _half(0, 50, hits=())
    current = _half(50, 40, hits=()) + _half(90, 10, hits=["r1"], decision="deny")
    # newest-first: current half is the list prefix (same as the 500-row query)
    out = live_rule_slip(current + prior, by_trace={}, by_entity={}, fp_cap=0.4)
    assert out["window"] == "ok"
    row = next(r for r in out["rules"] if r["rule_id"] == "r1")
    assert "fire_rate" in row["triggers"]
    assert row["hypothesis"] == "underpowered"
    assert row["miss_is_not_recall"] is True
    assert row["parked_draft"] is None


def test_mix_and_h2_successor_not_h1():
    prior = _half(0, 50, hits=["r1"], geo="US")
    misses = _half(50, 5, hits=(), y="1", geo="DE", decision="deny")
    hits = _half(55, 45, hits=["r1"], geo="DE")
    by_trace = {f"t{i}": "1" for i in range(50, 55)}
    out = live_rule_slip(
        misses + hits + prior, by_trace=by_trace, by_entity={}, fp_cap=0.4
    )
    row = next(r for r in out["rules"] if r["rule_id"] == "r1")
    assert "mix" in row["triggers"]
    assert row["hypothesis"] == "successor"
    assert row["miss_count"] >= 5


def test_h1_retire_not_h2():
    # 50+50 window; r1 fires at a new rate; 5 labeled FP hits; no leftover-fraud misses
    prior = _half(0, 50, hits=())
    labeled = [
        _row(50 + i, hits=["r1"], y="0", decision="deny", geo="US") for i in range(5)
    ]
    current_rest = _half(55, 45, hits=["r1"], geo="US")
    by_trace = {f"t{50 + i}": "0" for i in range(5)}
    out = live_rule_slip(
        labeled + current_rest + prior, by_trace=by_trace, by_entity={}, fp_cap=0.4
    )
    row = next(r for r in out["rules"] if r["rule_id"] == "r1")
    assert row["hypothesis"] == "retire"
    assert row["fp_rate"] > 0.4


def test_both_hypotheses_ambiguous():
    prior = _half(0, 50, hits=["r1"], geo="US")
    fps = [_row(50 + i, hits=["r1"], y="0", decision="deny", geo="DE") for i in range(5)]
    misses = [_row(55 + i, hits=(), y="1", geo="DE", decision="deny") for i in range(5)]
    rest = _half(60, 40, hits=["r1"], geo="DE")
    by_trace = {f"t{50 + i}": "0" for i in range(5)}
    by_trace.update({f"t{55 + i}": "1" for i in range(5)})
    out = live_rule_slip(
        fps + misses + rest + prior, by_trace=by_trace, by_entity={}, fp_cap=0.4
    )
    row = next(r for r in out["rules"] if r["rule_id"] == "r1")
    assert row["hypothesis"] == "ambiguous"


def test_resolve_y_trace_then_entity_ignores_proxy():
    row = _row(1, entity="e1")
    assert resolve_y(row, {"t1": "1"}, {}) == "1"
    assert resolve_y(row, {}, {"e1": "0"}) == "0"
    assert resolve_y(row, {"t1": "proxy"}, {"e1": "1"}) == "1"
    assert mix_value(row, "geo_country") == "US"
```

- [ ] **Step 2: Run** `cd services/decision-api && PYTHONPATH=src:.:../shared pytest tests/test_live_rule_slip.py -q` — expected FAIL import

- [ ] **Step 3: Implement** `live_rule_slip.py` (math only; no disk I/O)

```python
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from decision_api.rule_label_metrics import rule_precision_after_labels

MIX_FIELDS = ("event_type", "geo_country", "device_fingerprint", "canvas_hash")
MIN_HALF = 50
MIN_HITS = 5
MIN_MISSES = 5


def resolve_y(
    row: Mapping[str, Any],
    by_trace: Mapping[str, str],
    by_entity: Mapping[str, str],
) -> str | None:
    tid = str(row.get("trace_id") or "").strip()
    eid = str(row.get("entity_id") or "").strip()
    lab = by_trace.get(tid) if tid else None
    if lab not in {"0", "1"}:
        lab = by_entity.get(eid) if eid else None
    return lab if lab in {"0", "1"} else None


def mix_value(row: Mapping[str, Any], field: str) -> str:
    if field == "event_type":
        return str(row.get("event_type") or "").strip()
    snap = row.get("payload_snapshot")
    payload = snap.get("payload") if isinstance(snap, Mapping) else None
    blob = payload if isinstance(payload, Mapping) else snap if isinstance(snap, Mapping) else {}
    return str(blob.get(field) or "").strip()


def split_window(rows: Sequence[Mapping[str, Any]]) -> tuple[list, list, str]:
    items = [r for r in rows if isinstance(r, Mapping)]
    mid = len(items) // 2
    current, prior = list(items[:mid]), list(items[mid:])
    if len(current) < MIN_HALF or len(prior) < MIN_HALF:
        return current, prior, "underpowered"
    return current, prior, "ok"


def _hits(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("rule_hits")
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _rate(rule_id: str, half: Sequence[Mapping[str, Any]]) -> tuple[float, int]:
    n = len(half)
    h = sum(1 for r in half if rule_id in _hits(r))
    return ((h / n) if n else 0.0, h)


def _fire_rate_on(rule_id: str, current: Sequence[Mapping[str, Any]], prior: Sequence[Mapping[str, Any]]) -> bool:
    rc, hc = _rate(rule_id, current)
    rp, hp = _rate(rule_id, prior)
    if max(hc, hp) < MIN_HITS:
        return False
    if abs(rc - rp) >= 0.10:
        return True
    return rp > 0 and abs(rc - rp) / rp >= 0.5


def _dominant(rule_id: str, half: Sequence[Mapping[str, Any]], field: str) -> str:
    vals = [
        mix_value(r, field)
        for r in half
        if rule_id in _hits(r) and mix_value(r, field)
    ]
    if len(vals) < MIN_HITS:
        return ""
    return Counter(vals).most_common(1)[0][0]


def _mix_on(rule_id: str, current: Sequence[Mapping[str, Any]], prior: Sequence[Mapping[str, Any]]) -> bool:
    for field in MIX_FIELDS:
        a, b = _dominant(rule_id, current, field), _dominant(rule_id, prior, field)
        if a and b and a != b:
            return True
    return False


def live_rule_slip(
    rows: Sequence[Mapping[str, Any]],
    *,
    by_trace: Mapping[str, str],
    by_entity: Mapping[str, str],
    fp_cap: float,
    parked: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    current, prior, window = split_window(rows)
    empty = {
        "window": window,
        "fp_cap": fp_cap,
        "rules": [],
    }
    if window != "ok":
        return empty
    labeled = []
    for r in list(current) + list(prior):
        y = resolve_y(r, by_trace, by_entity)
        item = dict(r)
        item["y_label"] = y or ""
        labeled.append(item)
    prec = {
        str(x["rule_id"]): x
        for x in (rule_precision_after_labels(labeled).get("rules") or [])
        if x.get("rule_id")
    }
    ids = set()
    for r in list(current) + list(prior):
        ids.update(_hits(r))
    slot = {}
    for p in parked:
        ev = p.get("evidence") if isinstance(p.get("evidence"), Mapping) else {}
        lid = str(ev.get("live_rule_id") or "").strip()
        name = str(p.get("name") or "").strip()
        if lid and name and str(p.get("mode") or "shadow") == "shadow":
            if name.startswith("slip_retire_") or name.startswith("slip_successor_"):
                slot[lid] = name
    out_rules = []
    for rule_id in sorted(ids):
        triggers: list[str] = []
        if _fire_rate_on(rule_id, current, prior):
            triggers.append("fire_rate")
        if _mix_on(rule_id, current, prior):
            triggers.append("mix")
        if not triggers:
            continue
        metrics = prec.get(rule_id) or {}
        h1 = bool(metrics.get("enough_support")) and float(metrics.get("fp_rate") or 0) > fp_cap
        miss_n = 0
        for r in current:
            if resolve_y(r, by_trace, by_entity) == "1" and rule_id not in _hits(r):
                miss_n += 1
        h2 = miss_n >= MIN_MISSES and "mix" in triggers
        if h1 and h2:
            hyp = "ambiguous"
        elif h1:
            hyp = "retire"
        elif h2:
            hyp = "successor"
        else:
            hyp = "underpowered"
        out_rules.append(
            {
                "rule_id": rule_id,
                "triggers": triggers,
                "hypothesis": hyp,
                "fp_rate": metrics.get("fp_rate"),
                "labeled_hits": int(metrics.get("labeled_hits") or 0),
                "miss_count": miss_n,
                "miss_is_not_recall": True,
                "parked_draft": slot.get(rule_id),
                "park_reason": None,
            }
        )
    return {"window": "ok", "fp_cap": fp_cap, "rules": out_rules}
```

Rows passed in are newest-first (same as the 500-row query). `split_window` treats `[0:mid]` as current.

- [ ] **Step 4: Run** `pytest tests/test_live_rule_slip.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 2: Park helpers (no HTTP)

**Files:**
- Modify: `services/decision-api/src/decision_api/live_rule_slip.py`
- Modify: `services/decision-api/tests/test_live_rule_slip.py`

**Interfaces:**
- Consumes: `live_rule_slip(...)`, `get_active_packs_snapshot()`, `get_shadow_packs()`, `settings.rules_path`
- Produces:
  - `sanitize_rule_id(rule_id: str) -> str`
  - `find_live_rule(rule_id: str, packs: Sequence[Mapping]) -> dict | None`  # `{when, pack_file, score_delta}`
  - `existing_slip_slot(live_rule_id: str, packs: Sequence[Mapping]) -> str | None`
  - `build_retire_pack(rule_id, when, *, fp_rate, triggers) -> dict`
  - `build_successor_pack(live_rule_id, field, value, *, miss_count, triggers) -> dict | None`
  - `write_slip_pack(pack: dict) -> str`  # filename

- [ ] **Step 1: Tests**

```python
from decision_api.live_rule_slip import (
    build_retire_pack,
    build_successor_pack,
    existing_slip_slot,
    find_live_rule,
    sanitize_rule_id,
    write_slip_pack,
)


def test_sanitize_and_slot():
    assert sanitize_rule_id("r1/foo") == "r1_foo"
    assert existing_slip_slot(
        "r1",
        [{"name": "slip_retire_r1", "mode": "shadow", "evidence": {"live_rule_id": "r1"}}],
    ) == "slip_retire_r1"


def test_find_live_and_retire_shape():
    packs = [{"_source_file": "a.json", "mode": "active", "rules": [{"id": "r1", "when": [{"field": "amount", "op": "gt", "value": 10}], "score_delta": 20}]}]
    found = find_live_rule("r1", packs)
    assert found["when"][0]["field"] == "amount"
    pack = build_retire_pack("r1", found["when"], fp_rate=0.8, triggers=["fire_rate"])
    assert pack["mode"] == "shadow"
    assert pack["is_ai_authored"] is False
    assert pack["authored_by"] == "slip_critic"
    assert pack["rules"][0]["id"] == "r1"
    assert pack["rules"][0]["score_delta"] == 5
    assert pack["evidence"]["slip_kind"] == "retire"
    assert pack["evidence"]["miss_is_not_recall"] is True


def test_successor_legal_when_and_skip_unknown_field():
    pack = build_successor_pack("r1", "geo_country", "DE", miss_count=5, triggers=["mix"])
    assert pack["rules"][0]["score_delta"] == 15
    assert pack["rules"][0]["when"] == [{"field": "geo_country", "op": "eq", "value": "DE"}]
    assert pack["is_ai_authored"] is False
    assert build_successor_pack("r1", "not_a_field", "x", miss_count=5, triggers=["mix"]) is None


def test_write_slip_pack_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("RULES_PATH", str(tmp_path))  # if settings already loaded, monkeypatch settings.rules_path
    from decision_api.config import settings
    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    pack = build_retire_pack("r1", [{"field": "amount", "op": "gt", "value": 1}], fp_rate=0.9, triggers=["fire_rate"])
    name = write_slip_pack(pack)
    assert (tmp_path / name).is_file()
    assert name.startswith("slip_retire_")
```

If `RULES_PATH` env is not what `settings` reads, only `monkeypatch.setattr(settings, "rules_path", str(tmp_path))`.

- [ ] **Step 2: Run** — expected FAIL

- [ ] **Step 3: Implement** park helpers in the same module

`LEGAL_WHEN_FIELDS` = `event_type`, `geo_country`, `device_fingerprint`, `canvas_hash` (mix fields; all are in `_AI_PACK_ALLOWED_FIELDS`).

```python
import json
import re
from pathlib import Path

from decision_api.config import settings

_SAFE = re.compile(r"[^A-Za-z0-9_]+")
LEGAL_WHEN_FIELDS = frozenset(MIX_FIELDS)


def sanitize_rule_id(rule_id: str) -> str:
    return _SAFE.sub("_", (rule_id or "").strip())[:80] or "rule"


def find_live_rule(rule_id: str, packs: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    want = (rule_id or "").strip()
    for pack in packs:
        if str(pack.get("mode") or "active") not in {"active", ""}:
            continue
        for rule in pack.get("rules") or []:
            if not isinstance(rule, Mapping):
                continue
            if str(rule.get("id") or "").strip() == want:
                when = rule.get("when") if isinstance(rule.get("when"), list) else []
                return {
                    "when": list(when),
                    "pack_file": str(pack.get("_source_file") or ""),
                    "score_delta": rule.get("score_delta"),
                }
    return None


def existing_slip_slot(live_rule_id: str, packs: Sequence[Mapping[str, Any]]) -> str | None:
    want = (live_rule_id or "").strip()
    for p in packs:
        ev = p.get("evidence") if isinstance(p.get("evidence"), Mapping) else {}
        if str(ev.get("live_rule_id") or "").strip() != want:
            continue
        name = str(p.get("name") or "").strip()
        if name.startswith("slip_retire_") or name.startswith("slip_successor_"):
            if str(p.get("mode") or "shadow") == "shadow":
                return name
    return None


def build_retire_pack(rule_id: str, when: list, *, fp_rate: Any, triggers: list[str]) -> dict[str, Any]:
    safe = sanitize_rule_id(rule_id)
    return {
        "version": 1,
        "name": f"slip_retire_{safe}",
        "mode": "shadow",
        "is_ai_authored": False,
        "authored_by": "slip_critic",
        "rules": [{"id": rule_id, "when": list(when), "score_delta": 5}],
        "evidence": {
            "slip_kind": "retire",
            "live_rule_id": rule_id,
            "fp_rate": fp_rate,
            "triggers": list(triggers),
            "miss_is_not_recall": True,
        },
    }


def build_successor_pack(
    live_rule_id: str,
    field: str,
    value: str,
    *,
    miss_count: int,
    triggers: list[str],
) -> dict[str, Any] | None:
    if field not in LEGAL_WHEN_FIELDS or not str(value).strip():
        return None
    safe = sanitize_rule_id(live_rule_id)
    token = sanitize_rule_id(str(value))[:16]
    new_id = f"slip_{safe}_{token}"[:80]
    return {
        "version": 1,
        "name": f"slip_successor_{safe}",
        "mode": "shadow",
        "is_ai_authored": False,
        "authored_by": "slip_critic",
        "rules": [
            {
                "id": new_id,
                "when": [{"field": field, "op": "eq", "value": value}],
                "score_delta": 15,
            }
        ],
        "evidence": {
            "slip_kind": "successor",
            "live_rule_id": live_rule_id,
            "miss_count": miss_count,
            "mix_field": field,
            "mix_value": value,
            "triggers": list(triggers),
            "miss_is_not_recall": True,
        },
    }


def write_slip_pack(pack: Mapping[str, Any]) -> str:
    kind = str((pack.get("evidence") or {}).get("slip_kind") or "slip")
    safe = sanitize_rule_id(str((pack.get("evidence") or {}).get("live_rule_id") or "rule"))
    path = Path(settings.rules_path)
    path.mkdir(parents=True, exist_ok=True)
    fname = f"slip_{kind}_{safe}.json"
    target = (path / fname).resolve()
    if target.parent != path.resolve() or target.suffix != ".json":
        raise ValueError("slip path outside rules dir")
    if target.exists():
        return fname
    target.write_text(json.dumps(dict(pack), indent=2), encoding="utf-8")
    return fname
```

H2 dominant field of **misses** (for park, not just ping): add `successor_mix(current, rule_id, by_trace, by_entity) -> tuple[str, str] | None` — first MIX_FIELDS value that appears `>= 5` times among current `y=1` misses. Tests: DE geo on 5 misses → `("geo_country", "DE")`.

- [ ] **Step 4: Run** `pytest tests/test_live_rule_slip.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 3: `maybe_park_live_rule_slip` (tick, not GET)

**Files:**
- Modify: `services/decision-api/src/decision_api/live_rule_slip.py`
- Modify: `services/decision-api/tests/test_live_rule_slip.py`

**Interfaces:**
- Consumes: Task 1–2 + `SessionLocal` / optional `rows` for tests
- Produces: `async def maybe_park_live_rule_slip(tenant_id: str, *, rows=None, session=None) -> dict`  
  `{ "parked": [name], "skipped": [{rule_id, reason}] }`

- [ ] **Step 1: Tests** (tmp rules dir, in-memory rows — no DB)

```python
import pytest
from decision_api.live_rule_slip import maybe_park_live_rule_slip


@pytest.mark.asyncio
async def test_park_xor_and_dedup(tmp_path, monkeypatch):
    from decision_api.config import settings
    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    (tmp_path / "live.json").write_text(
        json.dumps({
            "version": 1, "name": "live", "mode": "active",
            "rules": [{"id": "r1", "when": [{"field": "amount", "op": "gt", "value": 1}], "score_delta": 20}],
        }),
        encoding="utf-8",
    )
    from decision_api.json_rules import load_rules
    load_rules()
    prior = _half(0, 50, hits=())
    labeled = [_row(50 + i, hits=["r1"], y="0", decision="deny") for i in range(5)]
    rest = _half(55, 45, hits=["r1"])
    rows = labeled + rest + prior
    by_trace = {f"t{50 + i}": "0" for i in range(5)}
    monkeypatch.setattr(
        "decision_api.live_rule_slip.load_y_maps",
        lambda tid: (by_trace, {}),
    )
    first = await maybe_park_live_rule_slip("demo", rows=rows)
    assert first["parked"]
    second = await maybe_park_live_rule_slip("demo", rows=rows)
    assert second["parked"] == []
    assert "already_parked" in {s["reason"] for s in second["skipped"]}
```

Add `load_y_maps(tenant_id) -> tuple[dict, dict]` wrapping `load_y_labels` so tests can monkeypatch.

Ambiguous rows → `parked == []` and skip reason `ambiguous`.

- [ ] **Step 2: Run** — expected FAIL

- [ ] **Step 3: Implement**

```python
async def maybe_park_live_rule_slip(
    tenant_id: str,
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    session: Any = None,
) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    if not tid:
        return {"parked": [], "skipped": [{"rule_id": "", "reason": "no_tenant"}]}
    by_trace, by_entity = load_y_maps(tid)
    from decision_api.leftover_promote_gate import leftover_caps_for_tenant
    from decision_api.json_rules import get_active_packs_snapshot, get_shadow_packs, load_rules

    _add, fp_cap, _min = leftover_caps_for_tenant(tid)
    slip_rows = list(rows) if rows is not None else await _load_slip_audit_rows(tid, session)
    slip = live_rule_slip(
        slip_rows, by_trace=by_trace, by_entity=by_entity, fp_cap=fp_cap, parked=get_shadow_packs()
    )
    parked: list[str] = []
    skipped: list[dict[str, str]] = []
    active = get_active_packs_snapshot()
    shadows = get_shadow_packs()
    for row in slip.get("rules") or []:
        rid = str(row.get("rule_id") or "")
        if existing_slip_slot(rid, shadows):
            skipped.append({"rule_id": rid, "reason": "already_parked"})
            continue
        hyp = row.get("hypothesis")
        if hyp not in {"retire", "successor"}:
            skipped.append({"rule_id": rid, "reason": str(hyp)})
            continue
        if hyp == "retire":
            found = find_live_rule(rid, active)
            if not found or not found.get("when"):
                skipped.append({"rule_id": rid, "reason": "no_live_when"})
                continue
            pack = build_retire_pack(
                rid, found["when"], fp_rate=row.get("fp_rate"), triggers=list(row.get("triggers") or [])
            )
        else:
            mix = successor_mix(slip_rows, rid, by_trace, by_entity)
            if not mix:
                skipped.append({"rule_id": rid, "reason": "no_legal_when"})
                continue
            pack = build_successor_pack(
                rid, mix[0], mix[1], miss_count=int(row.get("miss_count") or 0), triggers=list(row.get("triggers") or [])
            )
            if pack is None:
                skipped.append({"rule_id": rid, "reason": "no_legal_when"})
                continue
        fname = write_slip_pack(pack)
        load_rules()
        from decision_api.rule_api import _append_rule_change
        _append_rule_change(
            "park_live_rule_slip",
            fname,
            actor="slip_critic",
            detail={"live_rule_id": rid, "hypothesis": hyp},
        )
        parked.append(str(pack["name"]))
        shadows = get_shadow_packs()
    return {"parked": parked, "skipped": skipped}
```

`_load_slip_audit_rows`: if `session` is None, `async with SessionLocal()`. Same 500 query as leftover HIL. Include `rule_hits`.

`successor_mix`: current half only (`split_window` first list), count mix values on `y=1` misses, return first field with a value count `>= 5`.

- [ ] **Step 4: Run** `pytest tests/test_live_rule_slip.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 4: Fold into leftover GET + tick hooks

**Files:**
- Modify: `services/decision-api/src/decision_api/leftover_promote_gate.py` (`compute_desk_and_leftover_gates`)
- Modify: `services/decision-api/src/decision_api/calibration_api.py` (`shadow_promote_gate` return; `_tick_auto_promote`)
- Modify: `services/decision-api/src/decision_api/rule_api.py` (`auto_promote_tick`, `create_scout_pack`)
- Test: `services/decision-api/tests/test_live_rule_slip_api.py`
- Modify: `services/decision-api/tests/test_shadow_promote_gate_api.py` (GET source must not contain `maybe_park`)

**Interfaces:**
- Consumes: `live_rule_slip`, `maybe_park_live_rule_slip`
- Produces: GET body key `live_rule_slip`; tick returns `live_rule_slip_parked`

- [ ] **Step 1: Tests**

```python
from pathlib import Path
from decision_api.calibration_api import shadow_promote_gate


def test_get_source_does_not_park():
    src = Path("src/decision_api/calibration_api.py").read_text(encoding="utf-8")
    # shadow_promote_gate function body only
    assert "maybe_park_live_rule_slip" not in src.split("async def shadow_promote_gate")[1].split("async def ")[0]


def test_tick_source_parks():
    src = Path("src/decision_api/calibration_api.py").read_text(encoding="utf-8")
    assert "maybe_park_live_rule_slip" in src
```

Plus one async GET test (reuse `challenge_client` / existing fixture from `test_shadow_promote_gate_api.py`): response has `live_rule_slip.window` in `{"ok", "underpowered"}` and does not create `slip_*.json` in the rules dir.

- [ ] **Step 2: Run** — expected FAIL

- [ ] **Step 3: Implement**

In `compute_desk_and_leftover_gates`, inside the existing audit scan, also build:

```python
slip_rows = [{
    "trace_id": str(rec.trace_id),
    "entity_id": str(rec.entity_id or ""),
    "event_type": rec.event_type,
    "decision": rec.decision,
    "rule_hits": list(rec.rule_hits or []),
    "payload_snapshot": rec.payload_snapshot if isinstance(rec.payload_snapshot, dict) else {},
} for rec in records]
```

Then:

```python
from decision_api.live_rule_slip import live_rule_slip
from decision_api.json_rules import get_shadow_packs
slip = live_rule_slip(
    slip_rows, by_trace=y_by_trace, by_entity=y_by_entity, fp_cap=fp_rate_cap, parked=get_shadow_packs()
)
```

If no scan, `slip = {"window": "underpowered", "fp_cap": 0.4, "rules": []}`. Return it as `live_rule_slip`.

`shadow_promote_gate` adds `"live_rule_slip": gates["live_rule_slip"]`.

`_tick_auto_promote`:

```python
await maybe_auto_promote_shadow(tid)
from decision_api.live_rule_slip import maybe_park_live_rule_slip
await maybe_park_live_rule_slip(tid)
```

`auto_promote_tick`:

```python
out = await maybe_auto_promote_shadow(tenant_id)
parked = await maybe_park_live_rule_slip(tenant_id)
out["live_rule_slip_parked"] = parked
return out
```

`create_scout_pack`: after `maybe_auto_promote_shadow(tid)`, `await maybe_park_live_rule_slip(tid)` in the same `if tid` try.

- [ ] **Step 4: Run** `pytest tests/test_live_rule_slip_api.py tests/test_shadow_promote_gate_api.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 5: Scout clobber 409 + Promote does not strip

**Files:**
- Modify: `services/decision-api/src/decision_api/rule_api.py` (`create_scout_pack`)
- Modify: `services/decision-api/src/decision_api/live_rule_slip.py` (`slip_draft_would_clobber`)
- Test: `services/decision-api/tests/test_live_rule_slip_api.py`

**Interfaces:**
- Produces: `slip_draft_would_clobber(name: str, evidence: Mapping | None, shadow_packs) -> bool`

- [ ] **Step 1: Tests**

```python
def test_clobber_name_and_slot():
    from decision_api.live_rule_slip import slip_draft_would_clobber
    assert slip_draft_would_clobber("slip_retire_r1", None, [])
    assert slip_draft_would_clobber(
        "scout_x",
        {"live_rule_id": "r1"},
        [{"name": "slip_retire_r1", "mode": "shadow", "evidence": {"live_rule_id": "r1"}}],
    )
    assert not slip_draft_would_clobber("scout_x", {}, [])
```

HTTP: POST `/v1/rules/scout-pack` with `name=slip_retire_r1` → 409 `slip_draft_exists`.

Promote: write live pack with `r1`, write parked successor shadow, call `activate_shadow_pack` / Promote 200, read live file — `r1` still in `rules`.

- [ ] **Step 2: Run** — expected FAIL

- [ ] **Step 3: Implement**

```python
def slip_draft_would_clobber(name: str, evidence: Mapping[str, Any] | None, shadow_packs: Sequence[Mapping[str, Any]]) -> bool:
    n = (name or "").strip()
    if n.startswith("slip_retire_") or n.startswith("slip_successor_"):
        return True
    lid = str((evidence or {}).get("live_rule_id") or "").strip()
    return bool(lid and existing_slip_slot(lid, shadow_packs))
```

In `create_scout_pack`, before write:

```python
from decision_api.json_rules import get_shadow_packs
from decision_api.live_rule_slip import slip_draft_would_clobber
if slip_draft_would_clobber(body.name, None, get_shadow_packs()):
    raise HTTPException(409, "slip_draft_exists")
```

ScoutPackIn has no evidence field — name prefix is the 409. Slot check is for a later evidence field; still unit-test it.

Do **not** add `replaces_rule_id` to `activate_shadow_pack`.

- [ ] **Step 4: Run** `pytest tests/test_live_rule_slip_api.py tests/test_live_rule_slip.py -q` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

### Task 6: Observe card

**Files:**
- Create: `frontend/src/domain/liveRuleSlip.ts`
- Create: `frontend/src/domain/liveRuleSlip.test.ts`
- Modify: `frontend/src/api/client.ts` (`shadowPromoteGate` return type)
- Modify: `frontend/src/pages/OpsShadow.tsx`

**Interfaces:**
- Produces: `formatLiveRuleSlipLine(row) -> string`  
  e.g. `r1 · fire_rate · underpowered · ping only` or `r1 · mix · successor · slip_successor_r1`

- [ ] **Step 1: Tests**

```ts
import { describe, expect, it } from "vitest";
import { formatLiveRuleSlipLine } from "./liveRuleSlip";

describe("formatLiveRuleSlipLine", () => {
  it("ping only when no draft", () => {
    expect(
      formatLiveRuleSlipLine({
        rule_id: "r1",
        triggers: ["fire_rate"],
        hypothesis: "underpowered",
        parked_draft: null,
      }),
    ).toBe("r1 · fire_rate · underpowered · ping only");
  });
  it("names parked draft", () => {
    expect(
      formatLiveRuleSlipLine({
        rule_id: "r1",
        triggers: ["mix"],
        hypothesis: "successor",
        parked_draft: "slip_successor_r1",
      }),
    ).toBe("r1 · mix · successor · slip_successor_r1");
  });
});
```

- [ ] **Step 2: Run** `cd frontend && npm test -- --run src/domain/liveRuleSlip.test.ts` — expected FAIL

- [ ] **Step 3: Implement** helper + types + card

`LiveRuleSlip` type next to `LeftoverPromoteGate` in `client.ts`. Add `live_rule_slip?: LiveRuleSlip` on the `shadowPromoteGate` generic.

`OpsShadow.tsx`: extend `ShadowPromoteGate` with `live_rule_slip`. After the leftover-promote `</section>` (the block with `data-testid="leftover-promote-card"`), add:

```tsx
<section
  className="rounded-xl border border-surface-700 bg-surface-900 px-4 py-3 space-y-2"
  data-testid="live-rule-slip-card"
>
  <h2 className="text-sm font-semibold text-gray-200">Live rule slip</h2>
  {data?.live_rule_slip?.window === "underpowered" ? (
    <p className="text-xs text-gray-500">Window underpowered. No pings.</p>
  ) : null}
  <ul className="text-xs font-mono text-gray-300 space-y-1">
    {(data?.live_rule_slip?.rules || []).map((row) => (
      <li key={row.rule_id}>{formatLiveRuleSlipLine(row)}</li>
    ))}
  </ul>
  <p className="text-[11px] text-gray-500">
    Miss counts are leftover-born fraud, not recall. Promote does not strip the live rule.
  </p>
</section>
```

No Promote button on the row. Existing draft picker stays the path.

- [ ] **Step 4: Run** `npm test -- --run src/domain/liveRuleSlip.test.ts` — expected PASS

- [ ] **Step 5: Commit** — skip unless the user asked.

---

## Self-review (spec coverage)

| Spec requirement | Task |
|------------------|------|
| Window 500 split, `<50` half → no pings | 1 |
| Fire-rate ∪ mix opens ping | 1 |
| H1 xor H2 park; both/neither ping only | 1, 3 |
| `miss_is_not_recall` | 1, 6 |
| Host template, not AI-authored | 2 |
| One slot per live `rule_id`; no rewrite | 2, 3 |
| GET no write | 4 |
| Tick / y_label / scout-pack host parks | 4 |
| Auto-promote ignores slip files | 3 (is_ai_authored false; maybe_auto_promote unchanged) |
| Scout 409 clobber | 5 |
| Promote does not strip live rule | 5 |
| `/ops/shadow` card only | 6 |
| Brain wire rewrite | **out** |
| `replaces_rule_id` | **out** |
