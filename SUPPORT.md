# Support

Tarka is **source-available** under the **Elastic License 2.0**. Support is **community-only**.

There is **no SLA**, **no paid channel**, **no on-call**, and **no incident bridge**. Response time is whatever a volunteer maintainer can give.

## How to get help

Best-effort via [GitHub issues](https://github.com/pamu512/tarka/issues). That is not a production support contract.

## How to file an issue

Include:

- **service** (for example `core-api` / decision-api, case-api, investigation-agent)
- **tenant** (or `demo` / local)
- **trace_id** from the evaluate or case response
- What you expected versus what happened
- Compose files or Helm preset (`fraud-desk`, `prod-on-k8s`, …)
- Branch or commit SHA (development is on `master`)

Do not file undisclosed security vulnerabilities as public issues — see [SECURITY.md](SECURITY.md).

## GitLab-grade install (not claimed here)

A **GitLab-grade** claim is allowed **only** when G0–G8 have landed **and** a **named** pilot (internal or buyer) has signed the [production-install soak checklist](docs/docs/guides/production-install-soak-checklist.md). This page is not that sign-off and is not “primary decisioner” maturity.

Intended grade contract: [`docs/contracts/production-install-v1.md`](docs/contracts/production-install-v1.md) (G0 PR #405 — **not on `master`**). Helm catalog: [deployment.md](docs/docs/guides/deployment.md). Honesty lock: [CLAIM_LOCK](docs/compliance/CLAIM_LOCK.md).

Beta, no GA, no SOC 2 from us, beachhead CE (not banks), Elastic License 2.0 source-available (not OSS).
