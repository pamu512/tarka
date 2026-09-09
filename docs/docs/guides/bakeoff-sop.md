# Bake-off SOP (~1 week Observe)

Analyst path: enter Observe → watch leftover→draft, FP, promote TTL on `/ops/shadow` → Promote.

## Enter Observe

Mint or seed a pack in `mode=shadow`. AI-authored drafts need a backtest pass. Model never Promotes.

## Watch (EXAMPLE tenant policy — not product morals)

Example only: if leftover mint rate and FP cost stay inside **your** caps for ~1 week, consider Promote. Tarka does not ship a hardcoded FP threshold.

Ungated tenant → human Promote required. If `auto_promote` is explicitly on **and** provision caps pass → may auto-Promote. Default is off.

## Promote

Use desk Promote with a typed reason. Hop packs stay shadow until the same gated-or-human rule.

## Links

- [bakeoff-metrics-v1](../../../contracts/bakeoff-metrics-v1.md)
- [enforcement-v1](../../../contracts/enforcement-v1.md)
- [CLAIM_LOCK](../../compliance/CLAIM_LOCK.md)
- [analyst control loop](analyst-control-loop.md)
- [graph-analysis — Day-1 Hunt depth](graph-analysis.md#day-1-hunt-depth)
- [hunt-depth-v1](../../contracts/hunt-depth-v1.md)
