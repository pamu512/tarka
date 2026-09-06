# Baseline Assist (P-reg2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach one Python-computed share `event_count_1h_share_24h` on evaluate after 24h warmup, list it on the author catalog, and let packs FLAG on it — without Redis `rate`/`baseline_ratio` keys or a new Rust atom.

**Architecture:** A shared helper mutates the evaluate feature dict after Redis `compute_features`. The catalog grows a `computed[]` group (not a registry row). The name is reserved so overlay/map cannot steal it. Warmup is env until `desk_provision` (P-day1).

**Tech Stack:** Python 3 (decision-api + `services/shared`), FastAPI, existing JSON packs / Rust matcher unchanged, Vite frontend author-catalog types.

**Spec:** [2026-09-06-baseline-assist-design.md](../specs/2026-09-06-baseline-assist-design.md)

**Branch:** `honesty/baseline-assists` stacked on `#378` / `feat/desk-demo-vs-product`

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- No `rate` / `baseline_ratio` Redis keys. No new Rust `velocity_v1`. No `velocity()` in pack JSON.
- No new `counter_manifest` kind. No windows / baselines / hop etypes in the registry.
- No `desk_provision.json`. Warmup env: `TARKA_BASELINE_WARMUP_24H` default `10`.
- One assist only: `event_count_1h_share_24h`.
- Demo ≠ product. Do not change `make demo`, default-live demo packs, or clone-demo.
- No named third-party desks in published copy. Do not call Tarka OSS. Keep `scripts/oss/` path names.
- Do not change Redis `count()` to return `None`. Do not change the Rust pack matcher.

---

## File map

| File | Role |
|------|------|
| Create: `services/shared/baseline_assist.py` | `COMPUTED_NAME`, `DEFAULT_WARMUP_24H`, `COMPUTED_EXPLANATION`, `resolve_warmup_24h`, `apply_count_share` |
| Create: `services/decision-api/tests/test_baseline_assist.py` | Helper + warmup parse tests |
| Modify: `services/shared/field_registry.py` | `validate_registry_name` also rejects `COMPUTED_NAME` |
| Modify: `services/shared/author_catalog.py` | Always emit `computed[]`; `catalog_field_names` unions it |
| Modify: `services/decision-api/src/decision_api/evaluate/pipeline.py` | Call helper once after Redis/counter features land |
| Modify: `services/decision-api/src/decision_api/field_store.py` | Map target runs `validate_registry_name` (reserved → 400) |
| Modify: `frontend/src/domain/authorCatalog.ts` | `computed` on type + picker groups + `catalogFieldNames` |
| Modify: `frontend/src/domain/authorCatalogFallback.ts` | Fallback includes the one computed row |
| Modify: `docs/docs/guides/velocity-atoms.md` | Computed row + calibration pointer |
| Create: `docs/docs/guides/examples/event-count-1h-share-24h-pack.json` | Docs-only FLAG example |

---

### Task 1: Helper

**Files:**
- Create: `services/shared/baseline_assist.py`
- Create: `services/decision-api/tests/test_baseline_assist.py`

**Interfaces:**
- Consumes: `features` dict with optional `event_count_1h` / `event_count_24h`
- Produces: `COMPUTED_NAME = "event_count_1h_share_24h"`; `DEFAULT_WARMUP_24H = 10`; `COMPUTED_EXPLANATION = "event_count_1h / event_count_24h after 24h warmup; omitted when history is thin"`; `resolve_warmup_24h(raw: str \| None) -> int`; `apply_count_share(features: dict, warmup: int) -> None`

- [ ] **Step 1: Write the failing tests**

```python
from baseline_assist import (
    COMPUTED_NAME,
    DEFAULT_WARMUP_24H,
    apply_count_share,
    resolve_warmup_24h,
)


def test_omit_when_24h_below_warmup():
    feats = {"event_count_1h": 4, "event_count_24h": 9, "amount": 3}
    apply_count_share(feats, 10)
    assert COMPUTED_NAME not in feats
    assert feats["amount"] == 3


def test_share_when_warmup_met():
    feats = {"event_count_1h": 4, "event_count_24h": 10}
    apply_count_share(feats, 10)
    assert feats[COMPUTED_NAME] == 0.4


def test_omit_when_24h_zero():
    feats = {"event_count_1h": 0, "event_count_24h": 0}
    apply_count_share(feats, 10)
    assert COMPUTED_NAME not in feats


def test_zero_share_when_1h_empty_and_warmup_met():
    feats = {"event_count_24h": 10}
    apply_count_share(feats, 10)
    assert feats[COMPUTED_NAME] == 0.0


def test_omit_when_24h_missing_or_non_numeric():
    feats = {"event_count_1h": 4, "event_count_24h": "x"}
    apply_count_share(feats, 10)
    assert COMPUTED_NAME not in feats
    apply_count_share({"event_count_1h": 4}, 10)
    # no 24h key


def test_idempotent_clears_stale_share():
    feats = {"event_count_1h": 1, "event_count_24h": 2, COMPUTED_NAME: 0.99}
    apply_count_share(feats, 10)
    assert COMPUTED_NAME not in feats


def test_resolve_warmup():
    assert resolve_warmup_24h(None) == DEFAULT_WARMUP_24H
    assert resolve_warmup_24h("10") == 10
    assert resolve_warmup_24h("0") == 1
    assert resolve_warmup_24h("-3") == 1
    assert resolve_warmup_24h("nope") == DEFAULT_WARMUP_24H
    assert resolve_warmup_24h("  ") == DEFAULT_WARMUP_24H
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=services/shared python3 -m pytest -c services/decision-api/pytest.ini services/decision-api/tests/test_baseline_assist.py -q`

Expected: FAIL (import error)

- [ ] **Step 3: Implement**

```python
"""One computed velocity assist. Not a Redis key."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

COMPUTED_NAME = "event_count_1h_share_24h"
DEFAULT_WARMUP_24H = 10
COMPUTED_EXPLANATION = (
    "event_count_1h / event_count_24h after 24h warmup; omitted when history is thin"
)

_warmup_bad_logged = False


def resolve_warmup_24h(raw: str | None) -> int:
    """Parse TARKA_BASELINE_WARMUP_24H. Garbage → 10 (log once). <1 → 1."""
    global _warmup_bad_logged
    if raw is None or not str(raw).strip():
        return DEFAULT_WARMUP_24H
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        if not _warmup_bad_logged:
            log.warning("TARKA_BASELINE_WARMUP_24H invalid %r; using %s", raw, DEFAULT_WARMUP_24H)
            _warmup_bad_logged = True
        return DEFAULT_WARMUP_24H
    return n if n >= 1 else 1


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def apply_count_share(features: dict, warmup: int) -> None:
    """Set or delete COMPUTED_NAME. Never writes rate / baseline_ratio."""
    features.pop(COMPUTED_NAME, None)
    day = _as_number(features.get("event_count_24h"))
    if day is None or day < max(int(warmup), 1):
        return
    hour = _as_number(features.get("event_count_1h"))
    if hour is None:
        hour = 0.0
    features[COMPUTED_NAME] = hour / day
```

- [ ] **Step 4: Run tests to verify they pass**

Run: same as Step 2. Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/shared/baseline_assist.py services/decision-api/tests/test_baseline_assist.py
git commit -m "feat: add event_count_1h_share_24h helper"
```

---

### Task 2: Reserved name + catalog join

**Files:**
- Modify: `services/shared/field_registry.py` (`validate_registry_name`)
- Modify: `services/shared/author_catalog.py` (`build_author_catalog`, `catalog_field_names`)
- Modify: `services/decision-api/src/decision_api/field_store.py` (`upsert_map` — validate target name)
- Modify: `services/decision-api/tests/test_field_registry.py`
- Modify: `services/decision-api/tests/test_author_catalog.py`
- Modify: `services/decision-api/tests/test_field_api.py`

**Interfaces:**
- Consumes: `COMPUTED_NAME`, `COMPUTED_EXPLANATION` from `baseline_assist`
- Produces: catalog key `computed: list[{name, explanation}]` always length 1; `catalog_field_names` includes it; overlay/map 400 on that name

- [ ] **Step 1: Write failing tests**

In `test_field_registry.py`:

```python
from baseline_assist import COMPUTED_NAME

def test_validate_rejects_computed_assist_name():
    try:
        validate_registry_name(COMPUTED_NAME)
    except ValueError:
        return
    raise AssertionError(COMPUTED_NAME)
```

In `test_author_catalog.py`:

```python
def test_catalog_includes_computed_share():
    cat = build_author_catalog(graph_url="", growth_windows=None)
    assert cat["computed"] == [{
        "name": "event_count_1h_share_24h",
        "explanation": "event_count_1h / event_count_24h after 24h warmup; omitted when history is thin",
    }]
    allowed = ai_allowed_fields(cat)
    assert "event_count_1h_share_24h" in allowed
    assert "rate" not in allowed
    assert "baseline_ratio" not in allowed
```

In `test_field_api.py`:

```python
@pytest.mark.asyncio
async def test_put_overlay_and_map_reject_computed_name(client):
    r = await client.put(
        "/v1/fields/event_count_1h_share_24h",
        json={"explanation": "nope", "source": "new_feature"},
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 400
    m = await client.put(
        "/v1/fields/maps",
        json={"tenant_id": "t1", "buyer_key": "x", "registry_name": "event_count_1h_share_24h"},
    )
    assert m.status_code == 400
```

- [ ] **Step 2: Run to verify fail**

Run: `PYTHONPATH=services/shared:services/decision-api/src:services/shadow_agent python3 -m pytest -c services/decision-api/pytest.ini services/decision-api/tests/test_field_registry.py::test_validate_rejects_computed_assist_name services/decision-api/tests/test_author_catalog.py::test_catalog_includes_computed_share services/decision-api/tests/test_field_api.py::test_put_overlay_and_map_reject_computed_name -q`

Expected: FAIL

- [ ] **Step 3: Implement**

`field_registry.py` — import `COMPUTED_NAME` and reject it in `validate_registry_name` alongside `LEGACY_ALIASES`.

`author_catalog.py`:

```python
from baseline_assist import COMPUTED_EXPLANATION, COMPUTED_NAME

# in build_author_catalog return:
"computed": [{"name": COMPUTED_NAME, "explanation": COMPUTED_EXPLANATION}],

# catalog_field_names keys:
for key in ("redis", "growth", "payload", "computed"):
```

`field_store.upsert_map`: after strip, `registry_name = validate_registry_name(registry_name)` so reserved names 400 before the seed/overlay lookup.

- [ ] **Step 4: Run tests**

Same command as Step 2 plus `test_author_catalog.py` and `test_field_registry.py` full files. Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/shared/field_registry.py services/shared/author_catalog.py services/decision-api/src/decision_api/field_store.py services/decision-api/tests/test_field_registry.py services/decision-api/tests/test_author_catalog.py services/decision-api/tests/test_field_api.py
git commit -m "feat: catalog computed share; reserve the name"
```

---

### Task 3: Evaluate attach

**Files:**
- Modify: `services/decision-api/src/decision_api/evaluate/pipeline.py` (after the counter/agg `if/elif` that updates features, once)
- Modify: `services/decision-api/tests/test_evaluate_aggregate_gate.py`

**Interfaces:**
- Consumes: `apply_count_share`, `resolve_warmup_24h`
- Produces: evaluate feature dict may contain `event_count_1h_share_24h` only after warmup

- [ ] **Step 1: Write failing test**

Append to `test_evaluate_aggregate_gate.py`:

```python
@pytest.mark.asyncio
async def test_evaluate_omits_share_until_warmup(aggregate_eval_client, monkeypatch):
    monkeypatch.setenv("TARKA_BASELINE_WARMUP_24H", "10")
    c = aggregate_eval_client
    body = {
        "tenant_id": "share_tenant",
        "event_type": "payment",
        "entity_id": "share_entity",
        "role": "member",
        "payload": {"amount": 1.0},
    }
    r = await c.post("/v1/decisions/evaluate", json=body)
    assert r.status_code == 200
    feats, _ = c._captured[0]
    assert "event_count_1h_share_24h" not in feats
    assert "rate" not in feats
    assert "baseline_ratio" not in feats


@pytest.mark.asyncio
async def test_evaluate_attaches_share_when_counts_warm(aggregate_eval_client, monkeypatch):
    monkeypatch.setenv("TARKA_BASELINE_WARMUP_24H", "2")
    c = aggregate_eval_client
    body = {
        "tenant_id": "share_warm",
        "event_type": "payment",
        "entity_id": "share_warm_e",
        "role": "member",
        "payload": {"amount": 1.0},
    }
    for _ in range(3):
        r = await c.post("/v1/decisions/evaluate", json=body)
        assert r.status_code == 200
    feats, _ = c._captured[-1]
    assert feats["event_count_24h"] >= 2
    assert "event_count_1h_share_24h" in feats
    assert feats["event_count_1h_share_24h"] == feats["event_count_1h"] / feats["event_count_24h"]
```

- [ ] **Step 2: Run to verify fail**

Run: `PYTHONPATH=services/shared:services/decision-api/src python3 -m pytest -c services/decision-api/pytest.ini services/decision-api/tests/test_evaluate_aggregate_gate.py::test_evaluate_attaches_share_when_counts_warm -q`

Expected: FAIL (`event_count_1h_share_24h` missing)

- [ ] **Step 3: Wire pipeline**

In `pipeline.py` after the counter-service / local-agg block (after line ~786, before geo), one call. Counts used for the share are already computed; `record_event` already ran on local-agg paths and does not persist unknown field names (`NUMERIC_FIELDS` only).

```python
from baseline_assist import apply_count_share, resolve_warmup_24h

apply_count_share(
    features,
    resolve_warmup_24h(os.environ.get("TARKA_BASELINE_WARMUP_24H")),
)
```

Do not add `rate` / `baseline_ratio`. Do not write Redis.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=services/shared:services/decision-api/src python3 -m pytest -c services/decision-api/pytest.ini services/decision-api/tests/test_evaluate_aggregate_gate.py services/decision-api/tests/test_golden_counters.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/decision-api/src/decision_api/evaluate/pipeline.py services/decision-api/tests/test_evaluate_aggregate_gate.py
git commit -m "feat: attach count share on evaluate after warmup"
```

---

### Task 4: Desk catalog + docs

**Files:**
- Modify: `frontend/src/domain/authorCatalog.ts`
- Modify: `frontend/src/domain/authorCatalogFallback.ts`
- Modify: `frontend/src/domain/authorCatalog.test.ts`
- Modify: `docs/docs/guides/velocity-atoms.md`
- Create: `docs/docs/guides/examples/event-count-1h-share-24h-pack.json`
- Modify: `docs/docs/guides/examples/README.md` (one row)

**Interfaces:**
- Consumes: catalog `computed` from GET
- Produces: Computed picker group; fallback includes the row; docs example pack is not default-live

- [ ] **Step 1: Write failing frontend tests**

In `authorCatalog.test.ts` add `computed: []` to the hand-built catalog in the existing union test, and:

```typescript
it("includes computed share on fallback and picker", () => {
  const cat = fallbackAuthorCatalog();
  expect(catalogFieldNames(cat).has("event_count_1h_share_24h")).toBe(true);
  expect(cat.computed).toEqual([
    {
      name: "event_count_1h_share_24h",
      explanation: "event_count_1h / event_count_24h after 24h warmup; omitted when history is thin",
    },
  ]);
  const form = rulesPickerGroups(cat);
  expect(form.some((g) => g.category === "Computed" && g.fields.includes("event_count_1h_share_24h"))).toBe(true);
  const visual = featurePickerGroups(cat);
  expect(visual.some((g) => g.label === "Computed" && g.options.some((o) => o.name === "event_count_1h_share_24h"))).toBe(true);
});
```

Hand-built catalogs in this file and `leftoverVisualQuery.test.ts` / `seedCanvasFromLeftover.test.ts` that construct `AuthorCatalog` literals must add `computed: []` if TypeScript requires the field. Spreads of `fallbackAuthorCatalog()` pick it up automatically.

- [ ] **Step 2: Run to verify fail**

Run: `cd frontend && npx vitest run src/domain/authorCatalog.test.ts`

Expected: FAIL (type and/or assertion)

- [ ] **Step 3: Implement types + fallback + docs**

```typescript
export type AuthorCatalogComputed = { name: string; explanation: string };

export type AuthorCatalog = {
  redis: AuthorCatalogRedis[];
  growth: AuthorCatalogGrowth[];
  hops: Array<{ etype: string }>;
  payload: Array<{ name: string }>;
  computed: AuthorCatalogComputed[];
};

// catalogFieldNames: also for (const row of c.computed) names.add(row.name)

// featurePickerGroups: if catalog.computed.length, push { label: "Computed", options: [...] }
// rulesPickerGroups: if catalog.computed.length, push { category: "Computed", fields: [...] }
```

Fallback: `computed: [{ name: "event_count_1h_share_24h", explanation: "..." }]`.

`velocity-atoms.md` add a **Computed** row: `event_count_1h_share_24h` is not a Redis key; omitted when `event_count_24h` < `TARKA_BASELINE_WARMUP_24H` (default 10). `score_delta` on this assist is not a calibrated score (Observe calibration, later). Still no `rate` / `baseline_ratio`.

Example pack (docs only):

```json
{
  "version": 1,
  "name": "event_count_1h_share_24h_example",
  "mode": "shadow",
  "rules": [
    {
      "id": "share_1h_of_24h_high",
      "when": [{ "op": "gte", "field": "event_count_1h_share_24h", "value": 0.5 }],
      "tags": ["velocity:1h_share_24h"],
      "score_delta": 10,
      "description": "Half or more of the last 24h events landed in the last hour. Not a calibrated score."
    }
  ]
}
```

Do not add this file to default-live rule load paths.

- [ ] **Step 4: Run tests**

Run:

```
cd frontend && npx vitest run src/domain/authorCatalog.test.ts src/utils/leftoverVisualQuery.test.ts src/components/RuleBuilder/seedCanvasFromLeftover.test.ts
PYTHONPATH=services/shared:services/decision-api/src:services/shadow_agent python3 -m pytest -c services/decision-api/pytest.ini services/decision-api/tests/test_baseline_assist.py services/decision-api/tests/test_author_catalog.py services/decision-api/tests/test_field_registry.py services/decision-api/tests/test_field_api.py services/decision-api/tests/test_evaluate_aggregate_gate.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/domain/authorCatalog.ts frontend/src/domain/authorCatalogFallback.ts frontend/src/domain/authorCatalog.test.ts docs/docs/guides/velocity-atoms.md docs/docs/guides/examples/event-count-1h-share-24h-pack.json docs/docs/guides/examples/README.md docs/superpowers/specs/2026-09-06-baseline-assist-design.md docs/superpowers/plans/2026-09-06-baseline-assist.md
git commit -m "feat: desk computed picker and baseline assist docs"
```
