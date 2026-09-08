# EXAMPLE: promo consumer (emit_only)

Buyer promo service. Tarka does **not** deny promos itself.

```
# on webhook decision.emitted
if "deny_promo" in payload["suggested_actions"]:
    reject_redemption(payload.get("promo_id"), payload["trace_id"])
```

See [enforcement-v1](../contracts/enforcement-v1.md).
