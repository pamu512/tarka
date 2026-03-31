# Incident Response Runbook

## Trigger Conditions

- Decision API 5xx error rate > 2% for 5 minutes.
- p95 latency breach for 10 minutes.
- Event processing backlog growth beyond safe threshold.
- Data integrity discrepancy or security event.

## First 15 Minutes

1. Declare severity and open incident channel.
2. Assign incident commander and communications lead.
3. Freeze risky changes and capture active deploy/version state.
4. Validate blast radius (tenants, regions, services).

## Containment Steps

- Route traffic away from unhealthy instances.
- Disable optional enrichers via config flags if they cause cascade failures.
- Force safe defaults for non-critical asynchronous processors.
- Enable rule shadow mode for risky rule updates while triaging.

## Recovery Steps

- Roll forward with tested fix or roll back to last known good release.
- Replay failed events from dead-letter queue.
- Validate decision consistency and downstream case updates.
- Confirm all SLOs recovered before resolving.

## Postmortem Requirements

- Timeline with UTC timestamps.
- Root cause and contributing factors.
- Corrective and preventive actions with owners/dates.
- Detection and response gaps added to roadmap.
