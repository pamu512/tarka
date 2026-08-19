# Tarka

**Prove every signal.** Open-source, modular fraud decisioning you run yourself.

Tarka combines real-time **evaluate** (Rust JSON packs), **graph** topology, **cases/SAR**, and **local-first Shadow** forensics. `decision-api` owns allow/deny; Shadow, investigation, and trend **advise** only.

---

## Start here

| Doc | Purpose |
|-----|---------|
| [Quickstart](quickstart.md) | Lite compose → first decision |
| [Architecture](architecture.md) | Services and stores |
| [Feature data flows](guides/feature-data-flows.md) | How features move data and how decisions affect them |
| [SRE Compose profiles](operations/sre-compose-profiles.md) | Linux VM capacity, health, what pages |
| [Productionization](guides/repo-productionization-runbook.md) | Trend tick, honesty knobs, desk-strict |
| [STUB_REGISTER](../STUB_REGISTER.md) | Honesty ledger (no Potemkin APIs) |
| [Triad INDEX](../INDEX.md) | Operator hub |

## Compose paths

1. **Desk / day-1:** `infra/deploy/docker-compose.lite.yml` (+ fraud-desk overlay) → **core-api**
2. **Ingest rail:** `infra/deploy/docker-compose.v2-ingest.yml` → decision-api + orchestrator + shadow_agent
3. **Trend loop:** `--profile trend-tick` or `make trend-tick`

## Authority

| Actor | Can set production allow/deny? |
|-------|--------------------------------|
| decision-api evaluate | **Yes** |
| Shadow / trend / investigation | No — escalate, draft, cite |
| Analyst GitOps promote | Yes (human) |

See [feature data flows](guides/feature-data-flows.md) for diagrams.
