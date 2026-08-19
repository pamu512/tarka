# Support

Tarka is **Apache-2.0** open source. Support is **community-only**.

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
