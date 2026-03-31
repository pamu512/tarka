# Rules and Simulation

## Rule Engine

Tarka supports JSON-based rule packs with:
- condition operators
- score deltas
- tag output
- active/shadow/disabled modes

## Shadow Mode

Run candidate rules without affecting production decisions.
- Compare divergence vs production
- Inspect confusion trends and score drift

## Simulation

Use simulation to test changes safely before rollout:
- historical replay
- synthetic scenario generation
- A/B rule set comparison

## Recommendation Loop

Recommendation endpoints can propose rule candidates from observed patterns.
Always validate with simulation and shadow before activation.
