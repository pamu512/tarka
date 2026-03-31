# Enterprise Readiness

Tarka is production-ready when these controls are in place.

## Availability SLOs

- Decision API availability: 99.95% monthly.
- p95 decision latency: < 250ms (excluding external enrichment timeouts).
- Event delivery to stream sink: 99.9% within 60 seconds.

## Reliability Controls

- Multi-instance deployment for all stateless APIs.
- Connection pooling and bounded timeouts for all service-to-service calls.
- Graceful degradation when optional dependencies fail (NATS, enrichers, graph).
- Dead-letter and replay workflow for failed event processing.

## Security and Compliance Controls

- API key or SSO/RBAC enforcement for management APIs.
- PII masking/pseudonymization according to regional privacy profile.
- Immutable audit trails for every decision and case mutation.
- Change controls for rules, models, and policy bundles.

## Operational Readiness Checklist

- [ ] On-call schedule with primary/secondary coverage.
- [ ] Alert runbooks for Decision API, Case API, ML, and ingestion.
- [ ] Backup and restore validated in the last 30 days.
- [ ] Disaster recovery drill completed in the last quarter.
- [ ] Capacity test completed against expected peak throughput.

## Disaster Recovery Targets

- RTO: 4 hours.
- RPO: 15 minutes for transactional stores.

See `guides/incident-response.md` for incident process details.
