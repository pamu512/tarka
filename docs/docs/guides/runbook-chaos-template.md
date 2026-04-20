# Runbook template — chaos / fault injection

Copy this page for a **game day**, **release gate**, or **post-incident** record. Pair with [scripts/chaos/README.md](../../../scripts/chaos/README.md) for local Compose commands.

## Metadata

| Field | Value |
|--------|--------|
| **Title** | |
| **Date / timezone** | |
| **Owner** | |
| **Environment** | (e.g. local compose, dedicated staging cluster) |
| **Scope** | (services / tenants / regions) |

## Scenario

**Fault injected:** (e.g. Redis stop, Postgres stop, latency, packet loss)

**Hypothesis:** (what should break first, and how should the system behave?)

## Blast radius

- **User-visible impact:**
- **Data / correctness risk:**
- **Dependencies:** (graph, ML, OPA, NATS, ClickHouse, …)

## Preconditions

- [ ] Monitoring / logs accessible
- [ ] Rollback or recovery command documented below
- [ ] Stakeholders notified (if shared env)

## Execution steps

1.
2.
3.

## Signals observed

| Time | Signal | Expected? | Notes |
|------|--------|-------------|-------|
| | | | |

## Recovery

**Steps taken:**

**Time to healthy:**

## Outcome

- **Pass / fail vs hypothesis:**
- **Follow-ups:** (tickets, dashboards, alerts, docs)

## References

- Service SLOs: [service-slos-v1.md](./service-slos-v1.md)
- Resiliency backlog: [v1.2.5-execution-backlog-resiliency-etl-rules.md](./v1.2.5-execution-backlog-resiliency-etl-rules.md)
