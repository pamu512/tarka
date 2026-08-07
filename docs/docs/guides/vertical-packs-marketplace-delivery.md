# Marketplace vertical packs — install & pre-payout

Operator guide for Marketplace vertical packs: `marketplace`, `qcommerce`, `logistics`, `food_delivery`, and Track B `offline_payment` (COD / store pickup).

## End-to-end flow

Marketplace P0 ties three slices into one operator path: **pack install → pre-payout evaluate → durable hold → collusion triage**.

```text
1. Install pack (kill-gate)     → rules live for tenant
2. Evaluate at payout checkpoint → tags include action:payout_hold | action:payout_delay
3. integration-ingress           → durable hold row (source=durable)
4. CaseDetail multi-party rail   → graph neighbors + roles + linked cases
```

### 1. Install the marketplace pack

Use healthy simulation metrics so the kill gate passes (see [Install](#install-with-kill-gate) below). Confirm rules appear in the tenant rule list.

### 2. Evaluate at the pre-payout checkpoint

Send evaluate with `metadata.checkpoint=payout`, `metadata.payout_id`, and payload fields that match pack rules (e.g. low `account_age_days`, high velocity). Fired rules emit `action:payout_hold` or `action:payout_delay` tags.

```bash
curl -s -X POST -H "x-api-key: $TARKA_API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/v1/evaluate \
  -d '{
    "entity_id": "seller-abc",
    "payload": { "amount": 1200, "account_age_days": 10, "transaction_count_24h": 14 },
    "metadata": { "checkpoint": "payout", "payout_id": "po_1", "amount": 1200, "currency": "USD" }
  }' | jq '.tags'
```

Ensure decision-api has ingress wired:

```bash
export INTEGRATION_INGRESS_URL=http://integration-ingress:8010
export INGRESS_INTERNAL_TOKEN=<shared-secret>
```

### 3. Verify the durable hold

List holds from integration-ingress. Production rows use `source=durable` (not demo RNG aggregates).

```bash
curl -s -H "x-api-key: $TARKA_API_KEY" \
  "http://localhost:8010/v1/marketplace/payout-delay?tenant_id=demo" \
  | jq '.payouts[] | select(.payout_id=="po_1") | {payout_id, status, source, hold_reason, tags}'
```

Expect `status=held` (or `pending` for delay), `source=durable`, and hold reason derived from the triggering tag.

### 4. Triage collusion on CaseDetail

For a case anchored to the payee entity, fetch multi-party links:

```bash
curl -s -H "x-api-key: $TARKA_API_KEY" \
  "http://localhost:8020/v1/cases/{case_id}/multi-party-links?depth=3" | jq .
```

Open **CaseDetail** in the analyst UI. The **Multi-party links** rail (desktop sidebar / mobile panel) renders API data only: neighbor entities, role chips (`buyer`, `seller`, `courier`, `unknown`), propagated risk, path description, and links to related cases. When graph service is unavailable, the rail shows a degraded banner — roles are never invented client-side.

## Pack catalog

List available packs:

```bash
curl -s -H "x-api-key: $TARKA_API_KEY" \
  http://localhost:8000/v1/rules/vertical-packs | jq .
```

Each pack ships ≥5 rules with `kill_criteria` (min events, precision/recall floors, max FPR). Do not promote when simulation metrics fall outside the pack bands.

## Install (with kill-gate)

Install writes rules to the tenant rules path. The promote gate runs on supplied simulation metrics — low precision/recall returns **409 Conflict**.

```bash
# Healthy metrics → 201
curl -s -X POST -H "x-api-key: $TARKA_API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/v1/rules/vertical-packs/marketplace/install \
  -d '{
    "precision": 0.9,
    "recall": 0.9,
    "f1_score": 0.9,
    "false_positive_rate": 0.05,
    "events_evaluated": 500
  }' | jq .

# Bad metrics → 409 (kill gate blocks)
curl -s -X POST -H "x-api-key: $TARKA_API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/v1/rules/vertical-packs/marketplace/install \
  -d '{
    "precision": 0.1,
    "recall": 0.9,
    "f1_score": 0.2,
    "events_evaluated": 500
  }' | jq .
```

Replace `marketplace` with `qcommerce`, `logistics`, or `food_delivery` as needed.

## Promote (activate)

Promote is the same kill-gate contract on `/v1/rules/vertical-packs/{name}/promote`:

```bash
curl -s -X POST -H "x-api-key: $TARKA_API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/v1/rules/vertical-packs/qcommerce/promote \
  -d '{
    "precision": 0.9,
    "recall": 0.9,
    "f1_score": 0.9,
    "false_positive_rate": 0.05,
    "events_evaluated": 500
  }' | jq .
```

## Tag contract

Rules emit tags consumed by downstream enforcement (payout holds, delays, case routing):

| Tag prefix | Examples | Meaning |
| --- | --- | --- |
| `vertical:*` | `vertical:marketplace`, `vertical:food_delivery` | Pack origin |
| `action:payout_*` | `action:payout_hold`, `action:payout_delay` | Pre-payout enforcement verb |
| `risk:*` | `risk:collusion_shared_device`, `risk:promo_farm`, `risk:courier_spoof`, `risk:refund_burst`, `risk:multi_account_partner` | Typology for triage and graph rails |

Action tags fire when evaluate hits a matching rule. Risk tags label the abuse pattern for analysts and collusion graph assembly.

## Pre-payout checkpoint

A hold is created when evaluate fires `action:payout_hold` or `action:payout_delay` **and** the payout checkpoint matches:

- `metadata.checkpoint=payout`, **or**
- `event_type=payout` on the evaluate request

Also pass `metadata.payout_id` (required for the bridge). decision-api maps tags to durable row status/duration and POSTs to integration-ingress in the background; evaluate still returns 200 if hold create fails (bridge failure increments `payout_hold_bridge_failed`).

Configure decision-api:

```bash
export INTEGRATION_INGRESS_URL=http://integration-ingress:8010
export INGRESS_INTERNAL_TOKEN=<shared-secret>
```

### Hold vs delay

| Tag(s) fired | Durable `status` | Default duration |
| --- | --- | --- |
| `action:payout_hold` (alone or with delay) | `held` | 72h (`hold_duration_hours_default`) |
| `action:payout_delay` only | `pending` | 24h (`delay_hours_for_action_payout_delay`) |

If both tags fire, **hold wins**: `status=held` with hold duration.

Verify hold after evaluate:

```bash
curl -s -H "x-api-key: $TARKA_API_KEY" \
  "http://localhost:8010/v1/marketplace/payout-delay?tenant_id=demo" | jq '.payouts[] | select(.payout_id=="po_1")'
```

Example evaluate payload snippet:

```json
{
  "entity_id": "seller-abc",
  "event_type": "payout",
  "payload": { "amount": 1200, "account_age_days": 10, "transaction_count_24h": 14 },
  "metadata": { "checkpoint": "payout", "payout_id": "po_1", "amount": 1200, "currency": "USD" }
}
```

### Config flag: `honor_evaluate_action_tags`

Tenant payout-delay config stores `honor_evaluate_action_tags` (default `true`). In P1 the evaluate bridge **always** creates a hold when checkpoint + action tags match; the ingress flag is persisted for UI/future gateway use and does not gate the bridge yet.

## Webhooks (P1)

When `webhook_callback_url` is set on tenant payout-delay config, integration-ingress delivers marketplace webhooks after durable hold changes:

| Signal | When |
| --- | --- |
| `payout_hold` | After upsert that inserts a row or changes status into `held`/`pending` |
| `payout_release` | After successful release of an existing hold |

Webhook delivery failure does not roll back the hold transaction. Inspect delivery in marketplace webhook logs.

Configure callback URL via payout-delay config PATCH (tenant-scoped):

```bash
curl -s -X PATCH -H "x-api-key: $TARKA_API_KEY" -H "Content-Type: application/json" \
  "http://localhost:8010/v1/marketplace/payout-delay/config?tenant_id=demo" \
  -d '{"webhook_callback_url": "https://merchant.example/hooks/tarka"}' | jq .
```

## Mule automation (P1)

Mule sync runs **only** from explicit `mule_candidates` on tenant config — production list paths never invent `payout_id`s from SHA hashes or entity ids.

| Setting | Default | Behavior |
| --- | --- | --- |
| `automation_enabled` | `false` | List returns durable holds only (`source=durable`) |
| `mule_candidates` | `[]` | Each entry must include `payout_id`, `entity_id`; optional `mule_score`, amount/currency |

When `automation_enabled=true` and `mule_candidates` is non-empty, GET payout-delay may upsert from real candidates (`source=durable+automation`). For demos/tests, PATCH candidates explicitly; leave empty in production.

## Release

Release an existing hold:

```bash
curl -s -X POST -H "x-api-key: $TARKA_API_KEY" -H "Content-Type: application/json" \
  "http://localhost:8010/v1/marketplace/payout-delay/release?tenant_id=demo" \
  -d '{"payout_id": "po_1", "released_by": "analyst"}' | jq .
```

Release of a missing hold returns **404** (`payout hold not found`) — no synthetic success body. Internal create/release require `X-Internal-Token` when `INGRESS_INTERNAL_TOKEN` is configured (missing or wrong token → 401).

## Track B — COD / offline pack

Install pack id `offline_payment`. Evaluate with payload/metadata:

| Feature | Source |
| --- | --- |
| `payment_method` | `payload.payment_method` or `metadata.payment_method` (lowercased) |
| `is_cod` | method in `cod` / `cash_on_delivery` / `cash`, or `metadata.is_cod` |
| `is_offline_payment` | COD or `offline` / `store_pickup` / `pay_at_store` |

Rules emit `risk:cod_abuse`, `risk:address_hop`, `action:payout_hold` as configured.

## Track B — Redeem → loyalty-abuse bridge

When `metadata.checkpoint=redeem` or `event_type=redeem`, decision-api may call loyalty-abuse `POST /v1/evaluate` (fail-soft):

```bash
export LOYALTY_ABUSE_URL=http://loyalty-abuse:8080
export LOYALTY_ABUSE_API_KEY=<bearer>
```

Friction maps to tags `loyalty:friction:*`. Multi-gate LTV economics stay in the loyalty-abuse package — Tarka does not re-home them.

## Track B — Durable promo & seller boards

| Board | List | Record (S2S) |
| --- | --- | --- |
| Promo abuse | `GET /v1/analytics/promo-abuse` → `source=durable` | `POST /v1/internal/marketplace/promo-redemptions` |
| Seller integrity | `GET /v1/marketplace/seller-integrity` → `source=durable` | `POST /v1/internal/marketplace/seller-integrity` |

Empty tenants return empty rows (no SHA demo aggregates).

## Track C — Partner fusion proof

- L1 fixture: `python3 scripts/oss/partner_fusion_tenant_proof.py --mode fixture` (CI pin in `docs/compliance/partner-fusion-proof.stable.sha256`).
- L2 live requires real Fingerprint/Incognia credentials — status remains **WAIVED** without them (never forge LIVE pins). See [partner-fusion-proof-runbook.md](../../compliance/partner-fusion-proof-runbook.md).

## Verification

```bash
cd services/decision-api && PYTHONPATH=src python -m pytest \
  tests/test_payout_hold_from_evaluate.py tests/test_offline_payment_features.py \
  tests/test_loyalty_abuse_bridge.py tests/test_marketplace_vertical_packs.py -q
cd ../integration-ingress && python -m pytest \
  tests/test_payout_hold_store.py tests/test_payout_delay_durable.py \
  tests/test_promo_seller_durable.py tests/test_promo_abuse_tracking.py \
  tests/test_seller_integrity.py -q
cd ../case-api && PYTHONPATH=src:../shared:../../packages/shared-core python -m pytest tests/test_multi_party_links.py -q
cd ../../frontend && npm test -- --run MultiPartyLinks
python3 scripts/oss/partner_fusion_tenant_proof.py --mode fixture
```

## Internal references

Competitive maturity and grading docs are **private / internal only** — do not publish maturity numbers or grades externally:

- [CLAIM_LOCK.md](../../compliance/CLAIM_LOCK.md)
- [RATING_PRIVACY.md](../../compliance/RATING_PRIVACY.md)
