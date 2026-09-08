# EXAMPLE: payments consumer (emit_only)

Buyer payout system. Tarka does **not** implement holds.

```
# on webhook decision.emitted
if "hold_payout" in payload["suggested_actions"]:
    hold_payout(payload["entity_id"], reason=payload["trace_id"])
# ignore enforcement_action as authoritative unless enforcement_mode == handoff
```

See [enforcement-v1](../contracts/enforcement-v1.md).
