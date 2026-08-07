# Marketplace vertical packs — install & pre-payout

Operator guide for the four Marketplace P0 vertical packs: `marketplace`, `qcommerce`, `logistics`, and `food_delivery`.

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

Pass `metadata.checkpoint=payout` on evaluate requests at settlement time. When a fired rule carries `action:payout_hold` or `action:payout_delay`, the platform should hold or delay payout pending review (durable hold store wired in later Marketplace P0 slices).

Example evaluate payload snippet:

```json
{
  "entity_id": "seller-abc",
  "payload": { "amount": 1200, "account_age_days": 10, "transaction_count_24h": 14 },
  "metadata": { "checkpoint": "payout" }
}
```

## Loyalty-abuse boundary

LTV gates and multi-gate loyalty typologies remain owned by the **loyalty-abuse** package. These packs reuse **tag vocabulary only** (`risk:promo_farm`, etc.) — they do not import or re-home loyalty-abuse logic. Optional HTTP adapter may follow in a later slice.

## Internal references

Competitive maturity and grading docs are **private / internal only** — do not publish externally:

- [CLAIM_LOCK.md](../../compliance/CLAIM_LOCK.md)
- [RATING_PRIVACY.md](../../compliance/RATING_PRIVACY.md)
