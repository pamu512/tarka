# Tarka

**Prove every signal.** Local-first fraud OS you run yourself.

Tarka is evaluate-first: **decision-api** (Rust JSON packs) owns allow / deny / flag / review. Every decision has an audit trail; human overrides store why (`override → y_label`). Review / investigation is residual — born from evaluate deny / review. ALLOW never becomes a case. Graph is optional topological memory. Advise (LLM) is optional forensics / copilot, off until BYO. **Observe** is evaluate with `metadata.shadow` — not the LLM.

---

## Start here

| Doc | Purpose |
|-----|---------|
| [Quickstart](quickstart.md) | Lite compose → first decision |
| [Architecture](architecture.md) | Services and stores |
| [Feature data flows](guides/feature-data-flows.md) | How features move data and how decisions affect them |
| [GNN label loop](guides/gnn-label-loop.md) | Offline snapshot/export/holdout; serve off unless heuristic_v1 loses |
| [SRE Compose profiles](operations/sre-compose-profiles.md) | Linux VM capacity, health, what pages |
| [Productionization](guides/repo-productionization-runbook.md) | Trend tick, honesty knobs, desk-strict |
| [STUB_REGISTER](../STUB_REGISTER.md) | Honesty ledger (no Potemkin APIs) |
| [Operator hub](../INDEX.md) | Documentation index |

## Compose paths

1. **Evaluate-only / day-1:** `infra/deploy/docker-compose.lite.yml` (optional fraud-desk overlay) → **core-api** (evaluate + residual cases + thin desk). Agent / signal-api / ingress are overlays.
2. **Ingest rail (optional):** `infra/deploy/docker-compose.v2-ingest.yml` → orchestrator + shadow_agent (async ingest; not required for day-1)
3. **Trend loop (optional):** `--profile trend-tick` or `make trend-tick`

## Authority

| Actor | Can set production allow/deny? |
|-------|--------------------------------|
| decision-api evaluate | **Yes** |
| Advise / trend / investigation | No — escalate, draft, cite |
| Analyst GitOps promote | Yes (human) |

See [feature data flows](guides/feature-data-flows.md) for diagrams.
