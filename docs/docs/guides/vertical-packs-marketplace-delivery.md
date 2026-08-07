# Marketplace vertical packs — install & pre-payout

Operator guide for the four Marketplace P0 vertical packs: `marketplace`, `qcommerce`, `logistics`, and `food_delivery`.

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

Pass `metadata.checkpoint=payout` and `metadata.payout_id` on evaluate requests at settlement time. When a fired rule carries `action:payout_hold` or `action:payout_delay`, decision-api creates a durable hold via integration-ingress (background POST; evaluate still succeeds if hold create fails).

Configure decision-api:

```bash
export INTEGRATION_INGRESS_URL=http://integration-ingress:8010
export INGRESS_INTERNAL_TOKEN=<shared-secret>
```

Verify hold after evaluate:

```bash
curl -s -H "x-api-key: $TARKA_API_KEY" \
  "http://localhost:8010/v1/marketplace/payout-delay?tenant_id=demo" | jq '.payouts[] | select(.payout_id=="po_1")'
```

Example evaluate payload snippet:

```json
{
  "entity_id": "seller-abc",
  "payload": { "amount": 1200, "account_age_days": 10, "transaction_count_24h": 14 },
  "metadata": { "checkpoint": "payout", "payout_id": "po_1", "amount": 1200, "currency": "USD" }
}
```

## Loyalty-abuse boundary

LTV gates and multi-gate loyalty typologies remain owned by the **loyalty-abuse** package. These packs reuse **tag vocabulary only** (`risk:promo_farm`, etc.) — they do not import or re-home loyalty-abuse logic. Optional HTTP adapter may follow in a later slice.

## Verification

Automated suite (run from repo root paths):

```bash
cd services/decision-api && python -m pytest tests/test_marketplace_vertical_packs.py tests/test_payout_hold_from_evaluate.py -q
cd ../integration-ingress && python -m pytest tests/test_payout_hold_store.py tests/test_payout_delay_durable.py -q
cd ../case-api && python -m pytest tests/test_multi_party_links.py -q
cd ../../frontend && npm test -- --run MultiPartyLinks
```

Manual smoke (requires running stack: decision-api, integration-ingress, case-api, graph service, frontend):

| Step | Check |
| --- | --- |
| Install `marketplace` with healthy metrics | 201; rules in tenant listing |
| Evaluate `checkpoint=payout` + hold-firing features | Response tags include `action:payout_hold` |
| `GET /v1/marketplace/payout-delay?tenant_id=...` | Hold row with `source=durable` |
| CaseDetail with multi-party fixture data | Rail shows role chips + linked case hrefs |

When live services are unavailable, treat the automated suite as verification evidence; run the smoke checklist before production promotion.

## Internal references

Competitive maturity and grading docs are **private / internal only** — do not publish maturity numbers or grades externally:

- [CLAIM_LOCK.md](../../compliance/CLAIM_LOCK.md)
- [RATING_PRIVACY.md](../../compliance/RATING_PRIVACY.md)
