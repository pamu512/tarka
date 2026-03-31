# Support Policy

This document defines production support expectations for Tarka deployments.

## Support Tiers

- Community: best-effort via GitHub issues/discussions.
- Production: private support channel, response targets, and incident bridge.

## Severity and Targets

| Severity | Description | Initial Response | Mitigation Target |
| --- | --- | --- | --- |
| Sev-1 | Full outage or hard decisioning failure | 30 minutes | 4 hours |
| Sev-2 | Major degradation with workaround | 2 hours | 1 business day |
| Sev-3 | Partial impact, non-critical path | 1 business day | 3 business days |
| Sev-4 | Questions, docs, or minor defects | 2 business days | Planned release |

## Escalation

1. Open incident with affected service, region, tenant, and timestamps.
2. Include trace IDs and sample request IDs.
3. For Sev-1/2, activate incident bridge and page on-call.
4. Publish updates at least every 30 minutes for Sev-1.

## Required Operational Controls

- Health checks for all services.
- Alerting on API errors, queue lag, and latency SLO breaches.
- Backups and restore drills for stateful stores.
- Security patching cadence and dependency scans.
