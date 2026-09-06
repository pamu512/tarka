# Ingest data-agnostic + missing never false (P-ing1)

**Date:** 2026-09-06  
**Status:** Design — approved in chat; not implemented.  
**Branch:** `honesty/ingest-agnostic` stacked on P-reg1 (`#378` / `feat/desk-demo-vs-product`)  
**Related:** [field registry](./2026-09-05-field-registry-map-design.md), `packages/shared-core/tarka_shared/ingest_contract_v1.py`, `docs/docs/guides/ingest-contract-v1.md`, `services/decision-api/rules/device_signals.json`

## Goal

Open `event_type` past the closed six-name enum. Tarka SDK bools are present only when sent. Missing stays missing on glass — never invent `false` for an omitted collector signal.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- Empty plane URL = that plane off.
- No `rate` / `baseline_ratio`. No new Rust `velocity_v1`. No `velocity()` in pack JSON.
- No `desk_provision.json` (P-day1). Extra types via env until then.
- Demo ≠ product. Product overlay on Postgres. Demo PUT 403.
- No named third-party desks in published copy. Do not call Tarka OSS. Keep `scripts/oss/` path names.
- One public evaluate-shaped contract. Orchestrator `POST /v1/ingest` stays an adapter (already documented).
- Vendor enrichments stay features then map (P-reg1). This PR does not add a second map plane.

## Why now

`EventType` and `VALID_EVENT_TYPES` reject anything outside login / payment / signup / device / session / custom. A buyer `refund` cannot evaluate. Integrity already has missing≠false for `is_rooted` / `is_jailbroken` / `has_biometrics`. `device_signals` already uses `is_true` (omitted key does not fire). Golden/demo JSON still ships `is_bot: false` as if the SDK spoke. Feature snapshot copies `payload` as-is — omitted keys stay omitted unless a collector wrote `false`.

Rejected: unknown type silently becomes `custom`. Rejected: accept any regex with no allow-list. Rejected: taxonomy-only or missing-only split (both halves this PR).

## Units

### 1. Event type name

Same shape as a registry name: `^[a-z][a-z0-9_]{0,127}$`. Strip. Empty → `ingest_event_type_empty`.

Allow-list (union):

| Source | Contents |
|--------|----------|
| Seed | `login`, `payment`, `signup`, `device`, `session`, `custom` in bundled `event_types_v1.json` |
| Env | `TARKA_EVENT_TYPES` comma list (stripped, shape-checked; garbage tokens skipped, log once) |
| Tenant overlay | Product Postgres `event_types` (`tenant_id`, `name`). Demo: no durable write |

Unknown after union → `422` with `ingest_event_type_invalid` (evaluate and event-ingest). Same honesty as an unmapped pack field.

`EvaluateRequest.event_type` is a **string**, not the enum. Pydantic checks shape only (tenant overlay needs the session). Allow-list runs in evaluate / ingest after `tenant_id` is known. Existing `EventType` enum may remain as the six seed constants for tests; request parsing must accept a plain string.

Every `body.event_type.value` becomes the string (or `str(body.event_type)` if an enum instance is still passed in tests).

### 2. Shared helper

`packages/shared-core/tarka_shared/ingest_contract_v1.py` (decision-api and event-ingest already import `tarka_shared`):

- `SEED_EVENT_TYPES` — the six
- `validate_event_type_shape(name) -> str`
- `parse_env_event_types(raw: str | None) -> frozenset[str]`
- `allowed_event_types(overlay: frozenset[str], env: frozenset[str]) -> frozenset[str]`
- `validate_required_envelope_fields(..., allowed: frozenset[str])` — replace the hard-coded `VALID_EVENT_TYPES` check

Do not keep a closed `VALID_EVENT_TYPES` as the only gate.

### 3. Store + API

Table `event_types`: `tenant_id`, `name` (unique pair). Alembic after current decision-api head. Demo PUT 403 (`event types persist on product Postgres`).

`GET /v1/event-types?tenant_id=` → seed ∪ overlay ∪ env (sorted).  
`PUT /v1/event-types` body `{ tenant_id, name }` — analyst role, shape + not a duplicate seed (seed already allowed; overlay of a seed name is a no-op 200).  
No delete this PR.

Routes registered **above** any `/{name}` catch-all.

### 4. Missing ≠ false

SDK bool keys = `_SIGNAL_TAG_MAP` keys (already the device_signals set) plus payload twins `is_bot`, `is_emulator`, `is_vpn`, `is_rooted`, `ip_is_proxy`.

Rules:

- Key omitted or not a bool → do not write `False` onto features, tags, or integrity glass.
- `True` → copy / tag (today’s `extract_signal_tags` already requires `is True`).
- `False` sent by the SDK → copy as `False` (`is_false` may fire). That is present-false, not missing.
- `feature_snapshot_fallback` already does `dict(body.payload)` — do not add default `False` keys there.
- Collectors / demo seed / golden evaluate fixtures that invent `is_bot: false` (and the same for other SDK bools) **omit the key** unless the fixture’s job is “SDK sent false.”
- `integrity_presence` unchanged (already honest for its three keys).
- `device_signals.json` stays `is_true`. Add tests: omitted `is_bot` does not hit `sdk_bot`; explicit `false` does not hit `sdk_bot`; explicit `true` does.

### 5. Docs

- `ingest-contract-v1.md`: `event_type` is an allow-listed name (seed six + tenant + env), not a closed enum. Keep the adapter table. Dual envelope: one public evaluate-shaped contract; orchestrator maps in (already true — do not invent a second public envelope).
- Short note on `device_signals` / velocity-adjacent SDK page: packs fire on present `true` only.
- Do not write a second ingest guide.

## Data flow

1. Ingest or evaluate receives `event_type` string.
2. Shape check. Then allow-list(seed ∪ env ∪ overlay for `tenant_id`).
3. Fail → 422 `ingest_event_type_invalid`. Pass → existing pipeline; `event_type` on features/audit is the string.
4. Payload / `device_context.signals` SDK bools: copy only keys that are present bools.

## Error handling

- Overlay store down on evaluate allow-list load → seed ∪ env only (log once). Do not 500 a payment because types table is down; do not invent extra types.
- Env garbage token → skip that token, log once.
- Demo PUT overlay → 403.

## Testing

- `refund` not on allow-list → 422 evaluate and ingest contract helper.
- Overlay or `TARKA_EVENT_TYPES=refund` → `refund` accepted.
- Seed six still accepted.
- `EventCount` / empty / `tx_pay` → shape or invalid 422.
- Omitted `is_bot` → not in features; `device_signals` `sdk_bot` does not fire.
- Present `false` → feature is `False`; `sdk_bot` does not fire.
- Present `true` → `sdk_bot` fires.
- Golden/demo fixtures that are not “SDK said false” have no `is_bot: false` (and peers).
- Author catalog / ingest contract / device_signals / SDK integrity tests still pass.
- `walk_receipts` / default-live packs unchanged except if a live pack required invented false (none should).

## Success

A tenant can add `refund` and evaluate it. A request with no SDK bools does not look like “not a bot.” `device_signals` only FLAGs present `true`. Demo still works.

## Non-goals

- `desk_provision.json`. Observe calibration. P-graph1 hop sentences. P-reg2 share formula.
- Opening a second public ingest envelope.
- Changing Redis `count()` to `None`. New Rust atom.
- Feast / feature-store. Deleting the six seed names.
- Rewriting ML heuristic models that read `is_bot` (they already `safe_float` missing as 0 — out of scope unless a test requires it; do not teach evaluate to write 0).

## Done when

On a branch stacked on `#378`: `event_type` is an allow-listed string; unknown is 422; tenant/env can add `refund`; omitted SDK bools are missing on features and do not fire `device_signals`; golden/demo no longer invent `false`; ingest-contract doc matches; demo default-live path still runs.
