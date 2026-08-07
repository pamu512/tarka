# Location Enrichment Reweight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dual-write relatedness evidence and split risk fields; demote Geo in CaseDetail; elevate Graph + Loyalty gates; reweight docs — location is enrichment, not the linker.

**Architecture:** Shared builder emits `relatedness_evidence` (primary) and deprecated `location_cohort_evidence` (alias). `inference_build` adds `shared_device_risk` / `graph_peer_risk` / `geo_copresence_risk` while keeping `colocation_risk` as max composite. UI triage reorders; docs/matrix follow.

**Tech Stack:** Python decision-api, React CaseDetail, OpenAPI YAML, markdown guides.

**Spec:** `docs/superpowers/specs/2026-08-06-location-enrichment-reweight-design.md`

## Global Constraints

- Dual-write this release — do not remove `location_cohort_evidence` or `colocation_risk`.
- Never require location for evaluate success.
- Do not weaken impossible_travel / spoofed_location / trusted places.
- Loyalty card is advisory; must not imply order block.
- Use decision-api `.venv` for pytest; only stage task files (unrelated WIP exists).
- SCHEMA: `tarka.relatedness_evidence/v1`

## File map

| File | Role |
| --- | --- |
| `services/decision-api/src/decision_api/relatedness_evidence.py` | New primary builder |
| `services/decision-api/src/decision_api/location_cohort_evidence.py` | Thin alias / delegate |
| `services/decision-api/src/decision_api/inference_build.py` | Split risks |
| `services/decision-api/src/decision_api/evaluate/pipeline.py` | Dual-write snapshot |
| `services/decision-api/tests/test_relatedness_evidence.py` | New tests |
| `services/decision-api/tests/test_location_cohort_evidence.py` | Keep green via alias |
| `contracts/openapi/decision-api.yaml` | Document + deprecate |
| `frontend/src/pages/CaseDetail.tsx` | Triage reorder + Loyalty card |
| `frontend/src/components/CaseView/MetricHoverPanels.tsx` | Loyalty hover if needed |
| `docs/docs/guides/competitive-score-matrix-2026-04.md` | Reweight narrative |
| `docs/docs/guides/partner-enrichment-fusion.md` | Enrichment framing |
| `docs/docs/guides/tarka-gap-code-map.md` | Split graph vs geo |
| `docs/superpowers/canvases/maturity-4-0-regrade.canvas.tsx` | C2/C7 mitigated note |
| `services/decision-api/rules/graph_shared_device_v1.json` | Optional shadow pack |

---

### Task 0: Docs posture (matrix / fusion / gap / canvas)

**Files:**
- Modify: `docs/docs/guides/competitive-score-matrix-2026-04.md`
- Modify: `docs/docs/guides/partner-enrichment-fusion.md`
- Modify: `docs/docs/guides/tarka-gap-code-map.md` (section on co-location / graph)
- Modify: `docs/superpowers/canvases/maturity-4-0-regrade.canvas.tsx`

- [ ] **Step 1: Add short “Location = enrichment” callout** to matrix after three-bucket section: relatedness = graph + loyalty economics; Location pillar is hybrid enrichment not loyalty linker; C2/C7 product posture addressed by this program.

- [ ] **Step 2: partner-enrichment-fusion.md** — change any “score 4.0 on device/location” linker language to “partner enrichment quality (device fingerprint / location signals as optional).”

- [ ] **Step 3: tarka-gap-code-map.md** — separate bullets: graph entity linkage vs optional geo enrichment.

- [ ] **Step 4: Canvas** — under C2/C7 rows or Missed section, note “Product posture dual-write in progress / landed” without claiming S1 live pin closed.

- [ ] **Step 5: Commit**

```bash
git commit -m "docs: reweight location as enrichment vs graph and loyalty economics"
```

---

### Task 1: `relatedness_evidence` builder + alias

**Files:**
- Create: `services/decision-api/src/decision_api/relatedness_evidence.py`
- Modify: `services/decision-api/src/decision_api/location_cohort_evidence.py`
- Create: `services/decision-api/tests/test_relatedness_evidence.py`
- Keep: `tests/test_location_cohort_evidence.py` green

**Interfaces:**
- `RELATEDNESS_SCHEMA_ID = "tarka.relatedness_evidence/v1"`
- `build_relatedness_evidence(*, tags, inference_context, location_meta, graph_meta, partner_graph_hints=None, canary_cohort=None) -> dict | None`
- Shape:
```python
{
  "schema_id": RELATEDNESS_SCHEMA_ID,
  "graph": {...},           # peers, SEEN_AT hints
  "device": {...},          # shared_device tags/signals
  "geo_enrichment": {...},  # location_meta copresence/impossible_travel only when present
  "cohort": {...},          # optional canary
  "tags": [...],
}
```
- `build_location_cohort_evidence(...)` becomes wrapper that calls `build_relatedness_evidence` and returns **legacy shape** compatible with existing tests (same keys as today: schema_id tarka.location_cohort_evidence/v1 or keep old schema_id on alias only).

**Legacy alias rule:** When relatedness is non-None, also produce legacy dict with `schema_id = "tarka.location_cohort_evidence/v1"` and existing field layout (`cohort`, `copresence`, `graph`, `tags`) mapped from relatedness blocks so `test_location_cohort_evidence.py` still passes.

- [ ] **Step 1: Failing tests in `test_relatedness_evidence.py`**

```python
from decision_api.relatedness_evidence import (
    RELATEDNESS_SCHEMA_ID,
    build_relatedness_evidence,
)

def test_graph_peers_only_no_geo_block():
    ev = build_relatedness_evidence(
        tags=["sdk:shared_device"],
        inference_context={},
        location_meta={},
        graph_meta={"seen_at_peer_count_24h": 3},
    )
    assert ev is not None
    assert ev["schema_id"] == RELATEDNESS_SCHEMA_ID
    assert ev["graph"].get("seen_at_peer_count_24h") == 3
    assert "device" in ev
    # geo_enrichment absent or empty — no location_meta risks
    geo = ev.get("geo_enrichment") or {}
    assert not geo.get("copresence_risk")

def test_geo_enrichment_when_location_meta():
    ev = build_relatedness_evidence(
        tags=["location:copresence_elevated"],
        inference_context={"copresence_risk": 0.7},
        location_meta={"copresence_risk": 0.7},
        graph_meta={},
    )
    assert ev["geo_enrichment"]["copresence_risk"] == 0.7
```

- [ ] **Step 2: Implement builder + alias wrapper; run both test files**

```bash
cd services/decision-api && PYTHONPATH=src:../shared:../../packages/shared-core:../.. .venv/bin/python -m pytest tests/test_relatedness_evidence.py tests/test_location_cohort_evidence.py -q
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: relatedness_evidence primary with location_cohort alias"
```

---

### Task 2: Pipeline dual-write + inference risk split

**Files:**
- Modify: `services/decision-api/src/decision_api/evaluate/pipeline.py`
- Modify: `services/decision-api/src/decision_api/inference_build.py`
- Modify: `services/decision-api/tests/test_relatedness_evidence.py` or inference tests
- Modify: `contracts/openapi/decision-api.yaml` (inference_context + audit notes)

**Interfaces:**
- Pipeline: write `snap_extra["relatedness_evidence"]` and `snap_extra["location_cohort_evidence"]` (alias) when builder returns non-None.
- `build_inference_context` return includes:
  - `shared_device_risk`, `graph_peer_risk`, `geo_copresence_risk`, `colocation_risk=max(...)`

- [ ] **Step 1: Failing unit for risk split**

```python
def test_colocation_risk_is_max_of_split_components():
    from decision_api.inference_build import build_inference_context
    # Construct minimal call matching existing test_inference_build patterns
    # Assert shared_device_risk > 0 when sdk:shared_device
    # Assert geo_copresence_risk from location_meta only
    # Assert colocation_risk == max(shared_device_risk, graph_peer_risk, geo_copresence_risk)
    pass
```

Replace `pass` with real assertions using existing `test_inference_build.py` helpers/fixtures.

- [ ] **Step 2: Implement split in `inference_build.py`** (surgical: compute three floats, set colocation_risk = max; preserve impossible_travel logic untouched).

- [ ] **Step 3: Pipeline dual-write**

```python
from decision_api.relatedness_evidence import build_relatedness_evidence
from decision_api.location_cohort_evidence import build_location_cohort_evidence

rel = build_relatedness_evidence(...)
if rel is not None:
    snap_extra["relatedness_evidence"] = rel
legacy = build_location_cohort_evidence(...)  # alias
if legacy is not None:
    snap_extra["location_cohort_evidence"] = legacy
```

- [ ] **Step 4: OpenAPI** — describe new fields; deprecate note on `colocation_risk` / document `location_cohort_evidence` as deprecated alias.

- [ ] **Step 5: Pytest + commit**

```bash
git commit -m "feat: dual-write relatedness evidence and split colocation risk"
```

---

### Task 3: CaseDetail triage — Graph + Loyalty primary, Geo enrichment

**Files:**
- Modify: `frontend/src/pages/CaseDetail.tsx`
- Modify: `frontend/src/components/CaseView/MetricHoverPanels.tsx` (add LoyaltyEconomicsHoverBody if pattern fits)
- Test: existing CaseDetail/lean tests if any; add small unit test for flash-card builder if extracted

**Behavior:**
- Flash cards order: Velocity, Graph, Loyalty, Geo (enrichment).
- Loyalty value from `audit.payload_snapshot.loyalty_economics_gates` or decision audit path already loaded:
  - If missing: value `"Feeds req."` or `"—"`, tone neutral
  - If any gate `eligible === false` with status ok: `"Restricted"`, tone warn/critical
  - If all eligible true: `"Eligible"`, tone ok
  - If status feeds_missing/config_missing: `"Feeds req."`, tone neutral
- Geo card title: `"Geo (enrichment)"` or keep Geo with subtitle in hover: “Optional enrichment — not account linker.”
- Hover Loyalty: related ≠ abuse; dispatch/redeem/order; not order block.

- [ ] **Step 1: Implement card builder changes in CaseDetail** (find `scanLayerFlashCards` / similar ~line 115).

- [ ] **Step 2: Run frontend unit tests touching CaseDetail / leanNav if present**

```bash
npm --prefix frontend test -- --run src/pages/CaseDetail 2>/dev/null || npm --prefix frontend exec vitest run src/config/leanNav.test.ts
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: CaseDetail triage elevates graph and loyalty over geo linker"
```

---

### Task 4: Shadow graph shared-device rule pack (optional minimal)

**Files:**
- Create: `services/decision-api/rules/graph_shared_device_v1.json`
- Modify: `docs/docs/guides/loyalty-abuse-model-prerequisites.md` or location/graph guide one paragraph

- [ ] **Step 1: Shadow pack** targeting tags `sdk:shared_device` or `ring_shared_device` (match existing rule pack JSON style from `location_copresence_v1.json`), `shadow: true`, description “Graph/device relatedness — not geo linker.”

- [ ] **Step 2: Commit**

```bash
git commit -m "feat: shadow graph shared-device pack separate from geo copresence"
```

---

## Spec coverage

| Spec item | Task |
| --- | --- |
| Dual-write relatedness + alias | 1–2 |
| Split inference risks | 2 |
| OpenAPI deprecate notes | 2 |
| CaseDetail triage | 3 |
| Docs/matrix/canvas | 0 |
| Graph rule pack | 4 |
| Preserve impossible travel | 2 (no edits to travel block) |

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-06-location-enrichment-reweight.md`.

**1. Subagent-Driven (recommended)**  
**2. Inline Execution**

Which approach?
