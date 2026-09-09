# Bake-off SOP (~1 week Observe)

Analyst path: enter Observe → watch leftover→draft, FP, promote TTL on `/ops/shadow` → Promote.

## Enter Observe

Mint or seed a pack in `mode=shadow`. AI-authored drafts need a backtest pass. Model never Promotes.

## Watch (EXAMPLE tenant policy — not product morals)

Example only: if leftover mint rate and FP cost stay inside **your** caps for ~1 week, consider Promote. Tarka does not ship a hardcoded FP threshold.

Ungated tenant → human Promote required. If `auto_promote` is explicitly on **and** provision caps pass → may auto-Promote. Default is off.

## Promote

Use desk Promote with a typed reason. Hop packs stay shadow until the same gated-or-human rule.

## Warehouse consume (buyer SOP)

Buyer-owned. Tarka exports joinable receipts + labels; it does not host the lake or a case CRM.

EXAMPLE daily pull (same idempotency as [warehouse-sink-v1](../../../contracts/warehouse-sink-v1.md)):

```
# EXAMPLE cron — buyer host
15 2 * * * curl -fsS -H "Authorization: Bearer $TARKA_ANALYST_TOKEN" \
  "$TARKA_DECISION_URL/v1/exports/receipts?tenant_id=$TENANT&from=${FROM}&to=${TO}" \
  | lake_upsert --idempotency-key tenant,from,to,evaluation_token
```

Optional: re-ingest label facts via signed `POST /v1/webhooks/late-label`. Never Auto-Promote from labels.

## Links

- [bakeoff-metrics-v1](../../../contracts/bakeoff-metrics-v1.md)
- [enforcement-v1](../../../contracts/enforcement-v1.md)
- [warehouse-sink-v1](../../../contracts/warehouse-sink-v1.md)
- [label-join-v1](../../../contracts/label-join-v1.md)
- [CLAIM_LOCK](../../compliance/CLAIM_LOCK.md)
- [analyst control loop](analyst-control-loop.md)
