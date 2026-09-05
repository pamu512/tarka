# Leftover → Hunt → visual Observe + author catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One author catalog drives Redis counters, graph growth keys, leftover seed, and the visual/`/rules` picker; leftover Work → Hunt Draft → visual Observe save on the product desk.

**Architecture:** Manifest rows drive `compute_features`. Graph-service owns `GRAPH_GROWTH_WINDOWS` and two GETs. Decision-api `GET /v1/rules/author-catalog` unions redis + growth (via graph policy GET) + five hops + frozen payload. Evaluate copies `relation_growth_{window}` from the growth query when the graph plane is on. Desk leftover parse and pickers consume the catalog. Hop canvas node still compiles to `graph_v1` / `has_etype`. No new Rust atom.

**Tech Stack:** Python (shared aggregates, graph-service, decision-api), React Router + React Flow, vitest, pytest.

**Spec:** [docs/superpowers/specs/2026-09-05-leftover-hunt-visual-observe-design.md](../specs/2026-09-05-leftover-hunt-visual-observe-design.md)

**Branch:** implement on `feat/desk-demo-vs-product` (PR #377) so `DESK_PROFILE` exists. Worktree: `/Users/pamu/Documents/GitHub/tarka-wt/desk-demo-vs-product`.

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- Empty plane URL = that plane off. Graph keys **absent** when graph URL is empty (do not write `0` for missing plane / missing entity).
- Leftovers stay the queue. Work happens on Hunt. Do not unhide `/cases`.
- No `case.receipt_brief/v1`. No `rate` / `baseline_ratio`. No new Rust `velocity_v1`. No `velocity()` in pack JSON.
- Visual builder stays `RequireRole` RiskArchitect.
- Leftover-sourced save is Observe (`mode: shadow`). Do not call `force-live`.
- Demo is out of scope: no Draft on demo Hunt; do not change compose, `SentencePackPanel`, or clone-demo.
- Canvas + leftover hop allow-list is exactly `USES_DEVICE`, `HAS_EMAIL`, `HAS_PHONE`, `HAS_CARD`, `HAS_LIST`.
- Decision-api does **not** parse `GRAPH_GROWTH_WINDOWS`. Graph-service is the only parser.
- No named third-party desks in published copy.
- Do not commit unless the user asked. Skip **Step: Commit** otherwise.

---

## File map

| File | Responsibility |
|------|----------------|
| `services/shared/fraud_aggregates.py` | `compute_features` iterates validated manifest rows |
| `services/decision-api/src/decision_api/counter_manifest.py` | `valid_feature_outputs()`, fallback eleven names |
| `services/decision-api/tests/test_counter_manifest.py` | Manifest-driven compute + skip invalid row |
| `services/graph-service/src/graph_service/growth_policy.py` | Parse env; count edges in a window |
| `services/graph-service/tests/test_growth_policy.py` | Parse + count + routes |
| `services/graph-service/src/graph_service/main.py` | `GET /v1/graph/growth-policy`, `GET /v1/entities/{id}/relation-growth` |
| `services/graph-service/src/graph_service/entity_risk_score.py` | 1h/24h thresholds from policy |
| `services/decision-api/src/decision_api/author_catalog.py` | Build catalog JSON; AI field union |
| `services/decision-api/src/decision_api/rule_api.py` | `GET /v1/rules/author-catalog`; AI allow-list from catalog |
| `services/shadow_agent/pack_author_contract.py` | `ALLOWED_FIELDS` from catalog helper |
| `services/decision-api/src/decision_api/evaluate/enrichment.py` | Fetch relation-growth; attach keys |
| `services/decision-api/src/decision_api/evaluate/pipeline.py` | Attach growth after hops |
| `frontend/src/domain/authorCatalog.ts` | Types, fallback, field/hop parse helpers |
| `frontend/src/api/client.ts` | `rules.authorCatalog`, `graph.growthPolicy`, `graph.relationGrowth` |
| `frontend/src/utils/leftoverVisualQuery.ts` | Hunt + visual hrefs |
| `frontend/src/pages/Leftovers.tsx` | Work URL carries leftover_id / pack / hits |
| `frontend/src/domain/graphInvestigation.ts` | `growthOnly` uses policy |
| `frontend/src/components/GraphContextPanel.tsx` | Draft + queried growth lines |
| `frontend/src/components/RuleBuilder/compileHopEtype.ts` | Canvas hop → `emitHopPack` AST |
| `frontend/src/components/RuleBuilder/nodes/HopEtypeNode.tsx` | Palette node |
| `frontend/src/components/RuleBuilder/seedCanvasFromLeftover.ts` | Seed from query |
| `frontend/src/pages/Rules.tsx` | Picker from catalog (no `FIELD_CATALOG` hole) |
| `frontend/src/components/RuleBuilder/RuleBuilderCanvas.tsx` | Grouped Feature picker + leftover save copy |

---

### Task 1: Manifest-driven Redis compute

**Files:**
- Modify: `services/shared/fraud_aggregates.py`
- Modify: `services/decision-api/src/decision_api/counter_manifest.py`
- Modify: `services/decision-api/tests/test_counter_manifest.py`

**Interfaces:**
- Consumes: `counter_manifest_v1.json` `feature_outputs`
- Produces:

```python
DEFAULT_FEATURE_OUTPUTS: list[dict]  # today's eleven rows if manifest empty after skip

def valid_feature_outputs(raw: list | None) -> list[dict]:
    """Keep rows with name, known kind in {event_count,sum,avg,distinct}, window_seconds in (0, MAX_WINDOW]. Skip others."""

async def AggregateStore.compute_features(..., feature_outputs: list[dict] | None = None) -> dict:
    """Iterate valid_feature_outputs(feature_outputs or loaded manifest or DEFAULT)."""

def normalized_velocity_key_names() -> tuple[str, ...]:
    """Manifest names in file order (valid rows only)."""
```

- [ ] **Step 1: Write the failing tests**

Add to `test_counter_manifest.py`:

```python
@pytest.mark.asyncio
async def test_compute_features_emits_extra_manifest_row(monkeypatch):
    from decision_api.counter_manifest import valid_feature_outputs
    from fraud_aggregates import DEFAULT_FEATURE_OUTPUTS

    extra = list(DEFAULT_FEATURE_OUTPUTS) + [
        {"name": "event_count_6h", "kind": "event_count", "window_seconds": 21600}
    ]
    fake = FakeRedis()
    s = AggregateStore(redis_client=fake, clock=lambda: T0 + 120.0)
    await s.record_event("t", "e", "ev1", {"amount": 1.0}, ts=T0 + 1.0)
    feats = await s.compute_features("t", "e", {"amount": 1.0}, feature_outputs=extra)
    assert "event_count_6h" in feats
    assert "event_count_1h" in feats

@pytest.mark.asyncio
async def test_compute_features_skips_invalid_row():
    rows = [
        {"name": "event_count_1h", "kind": "event_count", "window_seconds": 3600},
        {"name": "nope", "kind": "rate", "window_seconds": 60},
        {"name": "", "kind": "event_count", "window_seconds": 3600},
    ]
    fake = FakeRedis()
    s = AggregateStore(redis_client=fake, clock=lambda: T0 + 120.0)
    feats = await s.compute_features("t", "e", {}, feature_outputs=rows)
    assert "event_count_1h" in feats
    assert "nope" not in feats
```

Keep `test_compute_features_keys_match_manifest_when_all_branches`.

- [ ] **Step 2: Run to verify fail**

Run: `cd services/decision-api && PYTHONPATH=src:../shared python3 -m pytest tests/test_counter_manifest.py -q`  
Expected: FAIL (`feature_outputs` unexpected kwarg and/or no `valid_feature_outputs`)

Confirm the local `PYTHONPATH` for this repo (existing tests already import `fraud_aggregates`). Use the same invocation as `tests/test_counter_manifest.py` already uses in CI / Makefile if different.

- [ ] **Step 3: Implement**

In `counter_manifest.py`:

- `valid_feature_outputs` as above. Unknown kind / bad window / missing name → skip (log in caller, not required in this module).
- If the file’s list is empty after skip, return `DEFAULT_FEATURE_OUTPUTS` from `fraud_aggregates`.
- `expected_feature_names()` uses `valid_feature_outputs`.

In `fraud_aggregates.py`:

- Export `DEFAULT_FEATURE_OUTPUTS` = today’s eleven dicts (same names/windows as the JSON).
- `compute_features`: for each valid row:
  - `event_count` → always `features[name] = await self.count(..., window_seconds)`
  - `sum` / `avg` → only if `row["field"]` is in `fields`
  - `distinct` → only if `fields.get(row["field"])` is truthy
- `normalized_velocity_key_names()` = tuple of valid names in order.

Do not add `rate`. Do not change `record_event`.

- [ ] **Step 4: Run tests**

Run: same pytest as Step 2  
Expected: PASS

- [ ] **Step 5: Commit** (only if asked)

```bash
git add services/shared/fraud_aggregates.py services/decision-api/src/decision_api/counter_manifest.py services/decision-api/tests/test_counter_manifest.py
git commit -m "feat: Redis counters driven by counter manifest"
```

---

### Task 2: Growth policy + query (graph-service)

**Files:**
- Create: `services/graph-service/src/graph_service/growth_policy.py`
- Create: `services/graph-service/tests/test_growth_policy.py`
- Modify: `services/graph-service/src/graph_service/main.py`
- Modify: `services/graph-service/src/graph_service/entity_risk_score.py`
- Modify: `contracts/openapi/graph-service.yaml` (two GET paths) if that file is how graph OpenAPI is kept in this repo

**Interfaces:**
- Consumes: incident edge timestamps (`coalesce(observed_at, created_at, updated_at)` — same as today’s 1h/24h)
- Produces:

```python
ALLOWED_GROWTH_WINDOWS = ("5m", "1h", "6h", "24h", "7d")
DEFAULT_GROWTH_WINDOWS_RAW = "1h:5,24h:15"

def parse_growth_windows(raw: str | None) -> list[tuple[str, int]]:
    """Drop unknown tokens. Empty after parse → default pair."""

def window_to_timedelta(window: str) -> timedelta: ...

def count_growth(timestamps: list, window: str, *, now: datetime | None = None) -> int:
    """Untimestamped / unparsable stamps excluded."""

def threshold_for(window: str, parsed: list[tuple[str, int]] | None = None) -> int | None:
    """1h → 5, 24h → 15 on default parse. Missing window → None."""
```

- [ ] **Step 1: Write the failing tests**

```python
from graph_service.growth_policy import count_growth, parse_growth_windows

def test_parse_growth_windows_default_and_drop_unknown():
    assert parse_growth_windows(None) == [("1h", 5), ("24h", 15)]
    assert parse_growth_windows("1h:5,6h:8,nope:1") == [("1h", 5), ("6h", 8)]
    assert parse_growth_windows("") == [("1h", 5), ("24h", 15)]

def test_count_growth_window_not_hardcoded_1h_only():
    from datetime import UTC, datetime, timedelta
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    stamps = [now - timedelta(minutes=10), now - timedelta(hours=3)]
    assert count_growth(stamps, "1h", now=now) == 1
    assert count_growth(stamps, "6h", now=now) == 2
    assert count_growth(stamps, "5m", now=now) == 0
```

- [ ] **Step 2: Run to verify fail**

Run: `cd services/graph-service && PYTHONPATH=src python3 -m pytest tests/test_growth_policy.py -q`  
Expected: FAIL import

- [ ] **Step 3: Implement parse/count + routes**

`GET /v1/graph/growth-policy` → `{ "windows": [{ "window": "1h", "threshold": 5 }, ...] }` from `parse_growth_windows(os.environ.get("GRAPH_GROWTH_WINDOWS"))`.

`GET /v1/entities/{entity_id}/relation-growth?tenant_id=&windows=`

- Load incident edge timestamps for that node (reuse collect used by `compute_entity_risk` / `_relation_growth_counts`). One helper; do not fork AGE/Neo4j/Janus count algorithms.
- `windows` optional. Empty / omitted → all configured windows.
- Unknown requested token → omit that window (200).
- Entity missing → 200, `{ "entity_id", "tenant_id", "windows": [{ "window", "count": null, "threshold" }] }`.
- Found entity → `count` is int (including `0`).

`entity_risk_score.py`: replace `FAST_GROWTH_1H` / `FAST_GROWTH_24H` literals with `threshold_for("1h")` / `threshold_for("24h")` (default still 5 and 15). Do not add score factors for 6h/7d.

- [ ] **Step 4: Run tests**

Run: `cd services/graph-service && PYTHONPATH=src python3 -m pytest tests/test_growth_policy.py tests/test_entity_risk_score.py -q`  
Expected: PASS

- [ ] **Step 5: Commit** (only if asked)

```bash
git add services/graph-service/src/graph_service/growth_policy.py services/graph-service/tests/test_growth_policy.py services/graph-service/src/graph_service/main.py services/graph-service/src/graph_service/entity_risk_score.py
git commit -m "feat: queryable graph growth windows from GRAPH_GROWTH_WINDOWS"
```

---

### Task 3: Author catalog GET + AI allow-list

**Files:**
- Create: `services/decision-api/src/decision_api/author_catalog.py`
- Create: `services/decision-api/tests/test_author_catalog.py`
- Modify: `services/decision-api/src/decision_api/rule_api.py` (`GET /author-catalog` **before** `/{filename}` routes; replace `_AI_PACK_ALLOWED_FIELDS` body)
- Modify: `services/shadow_agent/pack_author_contract.py` (`ALLOWED_FIELDS` built from the same helper — import from a tiny shared module or duplicate the frozen identity+alias sets only, catalog names from `author_catalog.catalog_field_names(growth=[])` plus aliases)

**Interfaces:**
- Consumes: Task 1 valid redis rows; Task 2 growth-policy JSON when `settings.graph_service_url` is set
- Produces:

```python
CATALOG_HOPS = ("USES_DEVICE", "HAS_EMAIL", "HAS_PHONE", "HAS_CARD", "HAS_LIST")
PAYLOAD_FIELDS = ("amount", "currency", "device_type", "is_bot", "is_emulator", "is_rooted", "is_vpn", "session_duration", "country", "ip_is_proxy", "distinct_countries_7d", "email_domain")
LEGACY_ALIASES = ("tx_count_1h", "tx_count_24h", "tx_amount_1h", "tx_amount_24h", "distinct_devices_24h", "distinct_ips_24h")
IDENTITY_FIELDS = (  # existing AI identity/SDK/geo/pay names already in _AI_PACK_ALLOWED_FIELDS that are not redis
    "event_type", "entity_id", "session_id", "acc_id", "user_id",
    "device_fingerprint", "canvas_hash", "webgl_vendor", "user_agent",
    "screen_resolution", "timezone_offset", "language", "platform", "vendor",
    "vendor_fingerprint_score", "vendor_incognia_risk", "ip_address", "ip_risk_score",
    "geo_country", "geo_city", "amount", "currency",
)

def window_token(window_seconds: int) -> str | None:
    """300→5m, 3600→1h, 21600→6h, 86400→24h, 604800→7d, else None (catalog still includes window_seconds)."""

def build_author_catalog(*, graph_url: str, growth_windows: list[dict] | None) -> dict:
    """redis from valid_feature_outputs; growth=[] if not graph_url or growth_windows is None; hops=CATALOG_HOPS; payload=PAYLOAD_FIELDS."""

def catalog_field_names(catalog: dict) -> frozenset[str]:
    """redis names + growth names + payload names."""

def ai_allowed_fields(catalog: dict) -> frozenset[str]:
    """catalog_field_names | IDENTITY_FIELDS | LEGACY_ALIASES. No rate / baseline_ratio."""
```

- [ ] **Step 1: Write the failing tests**

```python
from decision_api.author_catalog import build_author_catalog, ai_allowed_fields

def test_catalog_growth_empty_when_graph_off():
    cat = build_author_catalog(graph_url="", growth_windows=[{"window": "1h", "threshold": 5}])
    assert cat["growth"] == []
    names = {r["name"] for r in cat["redis"]}
    assert "event_count_7d" in names
    assert "avg_amount_1h" in names
    assert {h["etype"] for h in cat["hops"]} == {
        "USES_DEVICE", "HAS_EMAIL", "HAS_PHONE", "HAS_CARD", "HAS_LIST"
    }

def test_catalog_growth_from_policy_when_graph_on():
    cat = build_author_catalog(
        graph_url="http://graph.test",
        growth_windows=[{"window": "1h", "threshold": 5}, {"window": "24h", "threshold": 15}],
    )
    assert {g["name"] for g in cat["growth"]} == {"relation_growth_1h", "relation_growth_24h"}

def test_ai_allow_list_keeps_aliases_and_canonical():
    cat = build_author_catalog(graph_url="", growth_windows=None)
    allowed = ai_allowed_fields(cat)
    assert "tx_count_1h" in allowed
    assert "event_count_7d" in allowed
    assert "rate" not in allowed
    assert "baseline_ratio" not in allowed
```

- [ ] **Step 2: Run to verify fail**

Run: `cd services/decision-api && PYTHONPATH=src:../shared python3 -m pytest tests/test_author_catalog.py -q`  
Expected: FAIL import

- [ ] **Step 3: Implement**

`GET /v1/rules/author-catalog` (register **above** `/{filename}`):

- `graph_url = (settings.graph_service_url or "").strip()`
- If `graph_url`: HTTP GET `{graph_url}/v1/graph/growth-policy` with the same timeout as other graph reads; on any failure, `growth_windows = None` (empty growth).
- Return `build_author_catalog(...)`.
- Same auth as other `/v1/rules` GET reads (do not require the internal counters token).

`_validate_ai_authored_pack`: `field not in ai_allowed_fields(build_author_catalog(graph_url=settings.graph_service_url or "", growth_windows=None))` is wrong for growth — call `ai_allowed_fields` on a catalog built with live graph policy when URL set, else empty growth. Reuse the GET builder’s fetch helper so AI and the desk see the same growth keys.

`pack_author_contract.ALLOWED_FIELDS`: replace the handwritten velocity subset with `ai_allowed_fields(build_author_catalog(graph_url=os.environ.get("GRAPH_SERVICE_URL") or "", growth_windows=None))` **plus** the same identity/aliases (already inside `ai_allowed_fields`). If importing `decision_api` from shadow_agent is illegal (domain boundary), copy `ai_allowed_fields` + constants into `services/shared/author_catalog.py` and import from both. Prefer **one** shared module: `services/shared/author_catalog.py` if a decision-api import would fail CI domain-boundary tests. Check `test_domain_boundaries_gate` / similar; if decision-api import is fine from shadow_agent tests, keep it in decision-api and have shadow_agent import `author_catalog` via `PYTHONPATH`.

Do not add `rate`.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest services/decision-api/tests/test_author_catalog.py services/shadow_agent/tests/test_pack_author_contract.py -q` (use repo’s usual PYTHONPATH)  
Expected: PASS (existing AI tests still accept canonical + alias fields)

- [ ] **Step 5: Commit** (only if asked)

```bash
git add services/decision-api/src/decision_api/author_catalog.py services/decision-api/tests/test_author_catalog.py services/decision-api/src/decision_api/rule_api.py services/shadow_agent/pack_author_contract.py
git commit -m "feat: author catalog GET is the desk and AI field list"
```

---

### Task 4: Evaluate injects relation_growth keys

**Files:**
- Modify: `services/decision-api/src/decision_api/evaluate/enrichment.py`
- Modify: `services/decision-api/src/decision_api/evaluate/pipeline.py` (after `attach_hop_to_features`)
- Create: `services/decision-api/tests/test_relation_growth_features.py`

**Interfaces:**
- Consumes: Task 2 `GET /v1/entities/{id}/relation-growth`
- Produces:

```python
async def fetch_relation_growth(
    http: httpx.AsyncClient,
    tenant_id: str,
    entity_id: str,
) -> dict[str, Any] | None:
    """None if graph URL empty / graph missing-tagged / request fails."""

def attach_growth_to_features(features: dict, payload: dict | None) -> None:
    """For each window: count is int → features[f"relation_growth_{window}"] = count. count None → omit. Do not write 0 for null."""
```

- [ ] **Step 1: Write the failing tests**

```python
from decision_api.evaluate.enrichment import attach_growth_to_features

def test_attach_growth_writes_int_omits_null():
    feats: dict = {}
    attach_growth_to_features(feats, {
        "windows": [
            {"window": "1h", "count": 3, "threshold": 5},
            {"window": "24h", "count": None, "threshold": 15},
            {"window": "6h", "count": 0, "threshold": 8},
        ]
    })
    assert feats["relation_growth_1h"] == 3
    assert "relation_growth_24h" not in feats
    assert feats["relation_growth_6h"] == 0

def test_attach_growth_noop_on_none():
    feats = {"event_count_1h": 1}
    attach_growth_to_features(feats, None)
    assert feats == {"event_count_1h": 1}
```

- [ ] **Step 2: Run to verify fail**

Run: `cd services/decision-api && PYTHONPATH=src:../shared python3 -m pytest tests/test_relation_growth_features.py -q`  
Expected: FAIL import

- [ ] **Step 3: Implement**

`fetch_relation_growth`: if `not settings.graph_service_url` or `graph:missing` already in degrade tags, return None. GET `{graph}/v1/entities/{entity_id}/relation-growth?tenant_id=`. On HTTP/circuit error: return None (do not write keys, do not invent 0).

Pipeline: after `attach_hop_to_features`, `growth = await fetch_relation_growth(...)` then `attach_growth_to_features(features, growth)`. Skip when graph plane off / hop already tagged missing.

- [ ] **Step 4: Run tests**

Run: same pytest as Step 2  
Expected: PASS

- [ ] **Step 5: Commit** (only if asked)

```bash
git add services/decision-api/src/decision_api/evaluate/enrichment.py services/decision-api/src/decision_api/evaluate/pipeline.py services/decision-api/tests/test_relation_growth_features.py
git commit -m "feat: evaluate copies relation_growth windows when graph is on"
```

---

### Task 5: Frontend catalog + leftover Work URL

**Files:**
- Create: `frontend/src/domain/authorCatalog.ts`
- Create: `frontend/src/domain/authorCatalog.test.ts`
- Create: `frontend/src/domain/authorCatalogFallback.ts` (bundled redis names from current `feature_outputs` + five hops + payload; `growth: []`)
- Create: `frontend/src/utils/leftoverVisualQuery.ts`
- Create: `frontend/src/utils/leftoverVisualQuery.test.ts`
- Modify: `frontend/src/api/client.ts` (`rules.authorCatalog`)
- Modify: `frontend/src/pages/Leftovers.tsx`
- Modify: `frontend/src/pages/Leftovers.test.tsx`

**Interfaces:**
- Consumes: Task 3 GET shape
- Produces:

```ts
export type AuthorCatalog = {
  redis: Array<{ name: string; kind: string; window?: string; window_seconds: number; field?: string }>;
  growth: Array<{ name: string; kind: "growth"; window: string; threshold: number }>;
  hops: Array<{ etype: string }>;
  payload: Array<{ name: string }>;
};

export const CATALOG_HOPS = ["USES_DEVICE", "HAS_EMAIL", "HAS_PHONE", "HAS_CARD", "HAS_LIST"] as const;

export function catalogFieldNames(c: AuthorCatalog): Set<string>;
export function parseHopEtype(catalog: AuthorCatalog, ...raw: Array<string | null | undefined>): string | null;
export function parseVelocityField(catalog: AuthorCatalog, ...raw: Array<string | null | undefined>): string | null;

export function leftoverHuntSearch(row: {
  case_id: string;
  entity_id: string;
  tenant_id?: string;
  trace_id?: string;
  pack_id?: string;
  rule_hits?: string[];
}): URLSearchParams;

export function leftoverVisualHref(catalog: AuthorCatalog, q: {
  leftoverId?: string | null;
  pack?: string | null;
  hits?: string | null;
  hopNamed?: string | null;
  entityId?: string | null;
  tenantId?: string | null;
  decisionId?: string | null;
}): string;
```

- [ ] **Step 1: Write the failing tests**

```ts
import { fallbackAuthorCatalog } from "../domain/authorCatalogFallback";
import { leftoverHuntSearch, leftoverVisualHref, parseHopEtype, parseVelocityField } from "./leftoverVisualQuery";

const cat = {
  ...fallbackAuthorCatalog(),
  growth: [{ name: "relation_growth_1h", kind: "growth" as const, window: "1h", threshold: 5 }],
};

it("parses shipped hop etypes only", () => {
  expect(parseHopEtype(cat, "has_etype:USES_DEVICE")).toBe("USES_DEVICE");
  expect(parseHopEtype(cat, "HAS_LIST")).toBe("HAS_LIST");
  expect(parseHopEtype(cat, "graph:missing")).toBe(null);
  expect(parseHopEtype(cat, "has_etype:FAKE")).toBe(null);
});

it("parses catalog redis and growth names only", () => {
  expect(parseVelocityField(cat, "event_count_7d")).toBe("event_count_7d");
  expect(parseVelocityField(cat, "relation_growth_1h")).toBe("relation_growth_1h");
  expect(parseVelocityField(cat, "rate")).toBe(null);
});

it("prefers hop over field on the visual href", () => {
  const href = leftoverVisualHref(cat, {
    leftoverId: "c1", pack: "device_signals", hits: "event_count_1h",
    hopNamed: "has_etype:HAS_LIST", entityId: "buyer-1", tenantId: "demo", decisionId: "dec:tr-1",
  });
  const q = new URLSearchParams(href.split("?")[1]);
  expect(q.get("etype")).toBe("HAS_LIST");
  expect(q.get("field")).toBe(null);
});
```

Leftovers page: after Work, Hunt location includes `leftover_id`. Add `pack_id` / `rule_hits` on the fixture row if missing.

- [ ] **Step 2: Run to verify fail**

Run: `npm test -w tarka-ui -- --run src/utils/leftoverVisualQuery.test.ts`  
Expected: FAIL import

- [ ] **Step 3: Implement**

`parseHopEtype`: skip `graph:missing` / `graph:unavailable` / `graph:empty`; accept `has_etype:{X}` or raw if `X` is in `catalog.hops`.

`parseVelocityField`: raw equals a redis or growth `name`.

`leftoverVisualHref`: `from=leftover`; copy leftover_id/pack/hits/entity_id/tenant_id/decision_id; `etype` from hop parse; `field` only when etype is null.

`leftoverHuntSearch`: existing entity/tenant/decision_id plus leftover_id/pack/hits.

`rules.authorCatalog()` → GET `/v1/rules/author-catalog`.

Leftovers `workRow`: `navigate(\`/graph?${leftoverHuntSearch({ ...row, tenant_id: tenantId || "demo" })}\`)`.

Do not change `SentencePackPanel` or `VELOCITY_KEYS`.

- [ ] **Step 4: Run tests**

Run: `npm test -w tarka-ui -- --run src/utils/leftoverVisualQuery.test.ts src/domain/authorCatalog.test.ts src/pages/Leftovers.test.tsx`  
Expected: PASS

- [ ] **Step 5: Commit** (only if asked)

```bash
git add frontend/src/domain/authorCatalog.ts frontend/src/domain/authorCatalogFallback.ts frontend/src/utils/leftoverVisualQuery.ts frontend/src/pages/Leftovers.tsx frontend/src/pages/Leftovers.test.tsx frontend/src/api/client.ts
git commit -m "feat: leftover Work carries pack context; catalog parsers"
```

---

### Task 6: Hunt Draft + consume growth query

**Files:**
- Modify: `frontend/src/api/client.ts` (`graph.growthPolicy`, `graph.relationGrowth`)
- Modify: `frontend/src/domain/graphInvestigation.ts`
- Modify: `frontend/src/domain/graphInvestigation.test.ts`
- Modify: `frontend/src/components/GraphContextPanel.tsx`
- Modify: `frontend/src/pages/GraphInvestigationPage.tsx`

**Interfaces:**
- Consumes: Task 2 GET shapes; Task 5 `leftoverVisualHref`; `DESK_PROFILE` from `frontend/src/config/leanNav.ts`
- Produces:

```ts
export function nodeMeetsGrowthPolicy(
  counts: Record<string, number | null>,
  windows: Array<{ window: string; threshold: number }>,
): boolean;
```

- [ ] **Step 1: Write the failing filter test**

```ts
it("growthOnly uses policy thresholds not 5/15 literals", () => {
  expect(nodeMeetsGrowthPolicy({ "6h": 8 }, [{ window: "6h", threshold: 8 }])).toBe(true);
  expect(nodeMeetsGrowthPolicy({ "6h": 7 }, [{ window: "6h", threshold: 8 }])).toBe(false);
  expect(nodeMeetsGrowthPolicy({ "6h": null }, [{ window: "6h", threshold: 8 }])).toBe(false);
});
```

Remove `g1 >= 5 || g24 >= 15` from `keepWorkspaceNode`. `WorkspaceFilter` gains `growthWindows` + `growthCountsByNodeId` (or the page pre-filters). Fail closed if policy/query is down: `growthOnly` matches nothing (do not invent counts).

- [ ] **Step 2: Run to verify fail**

Run: `npm test -w tarka-ui -- --run src/domain/graphInvestigation.test.ts`  
Expected: FAIL `nodeMeetsGrowthPolicy`

- [ ] **Step 3: Wire client + dossier + Draft**

`graph.growthPolicy()` → GET `/v1/graph/growth-policy`  
`graph.relationGrowth(tenantId, entityId, windows?: string[])` → GET `/v1/entities/{id}/relation-growth`

Dossier: fetch `relationGrowth` for the selected entity. Render `data-testid="node-relation-growth"` as one span per returned window (`{window} {count ?? "—"}`). No `1h`/`24h` string literals in the JSX.

Draft: `DESK_PROFILE === "product"` AND (`leftover_id` on the Hunt query OR a pinned evaluate receipt). `data-testid="draft-observe-pack"`. Click → `leftoverVisualHref(catalog, ...)`. Hidden when `DESK_PROFILE === "demo"`. Hidden if graph plane off.

Load author catalog once for the href (fallback catalog if GET fails).

- [ ] **Step 4: Run tests**

Run: `npm test -w tarka-ui -- --run src/domain/graphInvestigation.test.ts`  
Expected: PASS. Add a small GraphContextPanel test if one already exists for Hold; otherwise assert Draft visibility in the existing page test file if present.

- [ ] **Step 5: Commit** (only if asked)

```bash
git add frontend/src/api/client.ts frontend/src/domain/graphInvestigation.ts frontend/src/domain/graphInvestigation.test.ts frontend/src/components/GraphContextPanel.tsx frontend/src/pages/GraphInvestigationPage.tsx
git commit -m "feat: Hunt Draft and growth from queried policy"
```

---

### Task 7: Hop etype canvas node

**Files:**
- Create: `frontend/src/components/RuleBuilder/compileHopEtype.ts`
- Create: `frontend/src/components/RuleBuilder/compileHopEtype.test.ts`
- Create: `frontend/src/components/RuleBuilder/nodes/HopEtypeNode.tsx`
- Modify: `frontend/src/components/RuleBuilder/compileToAST.ts` (`NODE_TYPES.hopEtype`, `isValidRuleConnection`)
- Modify: `frontend/src/components/RuleBuilder/validateRuleBuilderCanvas.ts`

**Interfaces:**
- Consumes: `emitHopPack`, `CATALOG_HOPS`
- Produces:

```ts
export function compileHopEtypeFromCanvas(nodes: Node[], edges: Edge[]):
  | { ok: true; etype: string; when_ast: { type: "graph_v1"; atom: "has_etype"; etype: string }; tags: string[] }
  | { ok: false };
```

- [ ] **Step 1: Write the failing test**

```ts
it("compiles HAS_LIST to the same when_ast as emitHopPack", () => {
  const nodes = [
    { id: "h1", type: "hopEtype", position: { x: 0, y: 0 }, data: { etype: "HAS_LIST" } },
    { id: "r1", type: "ruleRoot", position: { x: 0, y: 0 }, data: { ruleId: "h", tagsStr: "", scoreDeltaStr: "18", description: "" } },
  ];
  const edges = [{ id: "e", source: "h1", target: "r1", sourceHandle: "he-out", targetHandle: "r-in" }];
  const got = compileHopEtypeFromCanvas(nodes as never, edges as never);
  const pack = emitHopPack({ etype: "HAS_LIST" });
  const rule = (pack.rules as Array<{ when_ast: unknown; tags: string[] }>)[0];
  expect(got.ok).toBe(true);
  if (!got.ok) return;
  expect(got.when_ast).toEqual(rule.when_ast);
  expect(got.tags).toEqual(rule.tags);
});
```

- [ ] **Step 2: Run to verify fail**

Run: `npm test -w tarka-ui -- --run src/components/RuleBuilder/compileHopEtype.test.ts`  
Expected: FAIL import

- [ ] **Step 3: Implement**

Add `hopEtype: "hopEtype"` to `NODE_TYPES`.

`isValidRuleConnection`: `hopEtype` `he-out` → logicAnd `a-in` / logicOr `o-in` / ruleRoot `r-in` (same targets as Graph Risk).

`compileHopEtypeFromCanvas`: one rule root; its single incomer is `hopEtype`; etype in `CATALOG_HOPS`; return `emitHopPack({ etype }).rules[0]` when_ast + tags. `emitHopPack` already accepts `HAS_LIST` on this branch.

`HopEtypeNode`: select of `CATALOG_HOPS`, handle `he-out`.

`validateCanvasForAstSave`: if hop compile is ok, skip `compileFlowToJsonAst`.

Do not compile hop to `graph_score`.

- [ ] **Step 4: Run tests**

Run: `npm test -w tarka-ui -- --run src/components/RuleBuilder/compileHopEtype.test.ts src/components/RuleBuilder/compileToAST.test.ts`  
Expected: PASS

- [ ] **Step 5: Commit** (only if asked)

```bash
git add frontend/src/components/RuleBuilder/compileHopEtype.ts frontend/src/components/RuleBuilder/compileHopEtype.test.ts frontend/src/components/RuleBuilder/nodes/HopEtypeNode.tsx frontend/src/components/RuleBuilder/compileToAST.ts frontend/src/components/RuleBuilder/validateRuleBuilderCanvas.ts
git commit -m "feat: visual hop etype node emits graph_v1 has_etype"
```

---

### Task 8: Visual picker, leftover seed, `/rules` catalog

**Files:**
- Create: `frontend/src/components/RuleBuilder/seedCanvasFromLeftover.ts`
- Create: `frontend/src/components/RuleBuilder/seedCanvasFromLeftover.test.ts`
- Modify: `frontend/src/components/RuleBuilder/nodes/FeatureNode.tsx` (optgroup by kind from catalog)
- Modify: `frontend/src/components/RuleBuilder/RuleBuilderCanvas.tsx`
- Modify: `frontend/src/pages/VisualRuleBuilder.tsx`
- Modify: `frontend/src/pages/Rules.tsx` (replace hardcoded `FIELD_CATALOG` with catalog redis + payload + growth)

**Interfaces:**
- Consumes: Task 5 parsers + fallback catalog; Task 7 hop node
- Produces: `export function seedCanvasFromLeftover(catalog: AuthorCatalog, q: URLSearchParams): { nodes: Node[]; edges: Edge[] } | null`

- [ ] **Step 1: Write the failing tests**

```ts
const cat = { ...fallbackAuthorCatalog(), growth: [{ name: "relation_growth_1h", kind: "growth" as const, window: "1h", threshold: 5 }] };

it("seeds HAS_LIST hop when etype is shipped", () => {
  const seeded = seedCanvasFromLeftover(cat, new URLSearchParams("from=leftover&etype=HAS_LIST"));
  expect(seeded!.nodes.some((n) => n.type === "hopEtype" && (n.data as { etype: string }).etype === "HAS_LIST")).toBe(true);
});

it("does not seed a hop for etype=NOPE", () => {
  expect(seedCanvasFromLeftover(cat, new URLSearchParams("from=leftover&etype=NOPE"))).toBe(null);
});

it("seeds growth feature when field is in catalog", () => {
  const seeded = seedCanvasFromLeftover(cat, new URLSearchParams("from=leftover&field=relation_growth_1h"));
  expect(seeded!.nodes.some((n) => n.type === "feature" && (n.data as { field: string }).field === "relation_growth_1h")).toBe(true);
});
```

Rules test: if `Rules.test.tsx` exists, assert picker includes `event_count_7d` and `avg_amount_1h` from a mocked catalog. If no page test, add `frontend/src/domain/authorCatalog.test.ts` assertion that fallback redis names include those two (bundled manifest copy). Prefer a Rules picker test when the page already has tests.

- [ ] **Step 2: Run to verify fail**

Run: `npm test -w tarka-ui -- --run src/components/RuleBuilder/seedCanvasFromLeftover.test.ts`  
Expected: FAIL import

- [ ] **Step 3: Seed + banner + save + pickers**

`seedCanvasFromLeftover`: `from !== leftover` → null. Hop → root + hop + `he-out`→`r-in`. Else field → feature + operator (`gte`, `valueStr: "0"`) + root + wires. Else null.

Load catalog on visual + `/rules` (session cache; first fail → `fallbackAuthorCatalog()`).

Feature select: `<optgroup>` Count / Sum / Average / Distinct / Growth. Hide Growth when `growth.length === 0`.

`RuleBuilderCanvas`: register `HopEtypeNode`; Add “Hop etype”. Save: hop compile path sets `when_ast` / `tags`. If `from=leftover`, success copy: `Saved as Observe draft. Promote is not here.`

`VisualRuleBuilder` banner `data-testid="leftover-visual-banner"`: leftover id, pack or `missing`, hits or `—`. If seed null: `No shipped hop or catalog key on this leftover — pick from the palette.` Back link to `/graph?` with entity/decision/leftover params.

`/rules`: delete the handwritten velocity hole in `FIELD_CATALOG`; build categories from the fetched catalog.

- [ ] **Step 4: Run tests**

Run: `npm test -w tarka-ui -- --run src/components/RuleBuilder/seedCanvasFromLeftover.test.ts src/components/RuleBuilder/compileHopEtype.test.ts src/components/rbac/RequireRole.test.tsx`  
Expected: PASS

- [ ] **Step 5: Commit** (only if asked)

```bash
git add frontend/src/components/RuleBuilder frontend/src/pages/VisualRuleBuilder.tsx frontend/src/pages/Rules.tsx
git commit -m "feat: seed visual builder from leftover catalog keys"
```

---

### Task 9: Regression sweep

**Files:** none new

- [ ] **Step 1: Targeted tests**

```bash
npm test -w tarka-ui -- --run src/utils/leftoverVisualQuery.test.ts src/pages/Leftovers.test.tsx src/domain/graphInvestigation.test.ts src/domain/authorCatalog.test.ts src/components/RuleBuilder/compileHopEtype.test.ts src/components/RuleBuilder/seedCanvasFromLeftover.test.ts src/components/rbac/RequireRole.test.tsx src/utils/sentencePack.test.ts
cd services/graph-service && PYTHONPATH=src python3 -m pytest tests/test_growth_policy.py tests/test_entity_risk_score.py -q
cd services/decision-api && PYTHONPATH=src:../shared python3 -m pytest tests/test_counter_manifest.py tests/test_author_catalog.py tests/test_relation_growth_features.py -q
```

Expected: all PASS (adjust PYTHONPATH to match this repo’s existing test runner if different)

- [ ] **Step 2: Confirm no leftover 5/15 Hunt literals and no rate keys**

```bash
rg -n ">= 5|>= 15" frontend/src/domain/graphInvestigation.ts
rg -n "baseline_ratio|velocity_v1" frontend/src/components/RuleBuilder frontend/src/utils/leftoverVisualQuery.ts
```

Expected: no matches

- [ ] **Step 3: Mock-forbid + leftover fail-close**

```bash
python3 scripts/audit_prod_desk_mocks.py
```

Expected: OK

---

## Spec coverage

| Spec requirement | Task |
|------------------|------|
| Manifest drives `compute_features`; extra row / skip invalid | 1 |
| `GRAPH_GROWTH_WINDOWS` + policy/query GETs; 1h/24h risk thresholds | 2 |
| `GET /v1/rules/author-catalog`; AI aliases kept | 3 |
| Evaluate `relation_growth_*` when graph on; omit when off/null | 4 |
| Leftover Work leftover_id / pack / hits | 5 |
| parseHopEtype / parseVelocityField from catalog (incl. growth) | 5 |
| Product Hunt Draft; demo hidden; queried growth dossier | 6 |
| Hop node = `emitHopPack` AST | 7 |
| Seed hop / growth field / empty banner; Observe save; `/rules` picker | 8 |
| RequireRole 403; demo/sentences untouched; no 5/15 | 9 |
