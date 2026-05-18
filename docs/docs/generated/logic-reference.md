# YAML rule logic reference

!!! note "Generated"
    Generated at **2026-05-07T23:01:50.398740+00:00** by `scripts/docs/generate_rule_logic_docs.py` — do not edit by hand.

This page lists **compiler-style YAML** rules (Rust evaluator schema): boolean expressions over **signals**.
It does not enumerate Decision API JSON packs (`*.json`); see [Rule Authoring](rules.md).

## Scan roots

- `docs/examples/compiler-yaml-rules`
- `services/ml-scoring/rules`

## Summary

- **Rules documented:** 2
- **Unique rule ids:** 2

## Rule index

| Rule ID | Source | Signals | Logic (summary) | Benchmark | Detail |
| --- | --- | --- | --- | --- | --- |
| `high_value_wire` | `docs/examples/compiler-yaml-rules/fraud_guards_example.yaml` | `payment_amount_usd`, `payment_risk_score` | (payment_amount_usd gte 5000 AND payment_risk_score gte 70) | [tarka-core Criterion regression (CI workflow)](https://github.com/tarka/tarka/blob/main/.github/workflows/tarka-core-benchmark-regression.yml) | [Jump](#high_value_wire-a6ec2a22669d) |
| `geo_block` | `docs/examples/compiler-yaml-rules/fraud_guards_example.yaml` | `ip_country` | ip_country eq "XX" | [tarka-core Criterion regression (CI workflow)](https://github.com/tarka/tarka/blob/main/.github/workflows/tarka-core-benchmark-regression.yml) | [Jump](#geo_block-4a2892d4ed9d) |

## Rule details

### high_value_wire {#high_value_wire-a6ec2a22669d}

- **Source:** `docs/examples/compiler-yaml-rules/fraud_guards_example.yaml`
- **Rule set version:** `1`
- **Signals:** `payment_amount_usd`, `payment_risk_score`
- **Logic:**
    (payment_amount_usd gte 5000 AND payment_risk_score gte 70)

- **Benchmark (tarka-core Criterion regression (CI workflow)):** [https://github.com/tarka/tarka/blob/main/.github/workflows/tarka-core-benchmark-regression.yml](https://github.com/tarka/tarka/blob/main/.github/workflows/tarka-core-benchmark-regression.yml)

#### YAML excerpt

```yaml
id: high_value_wire
expression:
  kind: and
  children:
  - kind: compare_signal
    signal_name: payment_amount_usd
    op: gte
    expected: 5000
  - kind: compare_signal
    signal_name: payment_risk_score
    op: gte
    expected: 70
```

### geo_block {#geo_block-4a2892d4ed9d}

- **Source:** `docs/examples/compiler-yaml-rules/fraud_guards_example.yaml`
- **Rule set version:** `1`
- **Signals:** `ip_country`
- **Logic:**
    ip_country eq "XX"

- **Benchmark (tarka-core Criterion regression (CI workflow)):** [https://github.com/tarka/tarka/blob/main/.github/workflows/tarka-core-benchmark-regression.yml](https://github.com/tarka/tarka/blob/main/.github/workflows/tarka-core-benchmark-regression.yml)

#### YAML excerpt

```yaml
id: geo_block
expression:
  kind: compare_signal
  signal_name: ip_country
  op: eq
  expected: XX
```

## Benchmark linking

Per-rule Criterion URLs are optional: the OSS repo publishes **suite-level** `tarka-core` benches (see workflow above). Copy `docs/benchmark-links.example.json` to a manifest path your team controls, add `per_rule` URLs (CI artifacts, Grafana, internal perf dashboards), and pass `--benchmark-manifest` when generating this page.

