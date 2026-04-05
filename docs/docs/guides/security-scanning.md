# Security scanning (maintainers)

## Where results appear

| Mechanism | Workflow | Output |
|-----------|-----------|--------|
| **Trivy** (filesystem + decision-api image) | [.github/workflows/security-scan.yml](../../../.github/workflows/security-scan.yml) | SARIF uploaded to **GitHub → Security → Code scanning** (when available for the repo). Table output in job logs. |
| **Dependabot** | [.github/dependabot.yml](../../../.github/dependabot.yml) | **Pull requests** grouped by ecosystem; review + CI before merge. |
| **CodeQL** | [.github/workflows/codeql.yml](../../../.github/workflows/codeql.yml) | Static analysis alerts (if enabled). |

Forks and some plan tiers may not show SARIF uploads; logs still contain Trivy tables.

### Code scanning vs. GitHub Issues

**Security → Code scanning** (e.g. `https://github.com/<owner>/<repo>/security/code-scanning`) lists **alerts** from uploaded SARIF (here: mostly **Trivy** on the repo filesystem and the **decision-api** Docker image). That count is **not** the same as **Issues**.

A large open count (e.g. **~98**) is often **Debian/Ubuntu packages inside `python:*-slim`** (util-linux, zlib, glibc, etc.): real CVE metadata, but many have **no fixed package** in the distro yet, or **no exploitable path** in a minimal API container. Triage in the UI with **Dismiss** (reason: *false positive*, *used in tests*, *risk accepted*, *won’t fix*) or wait for **new SARIF uploads** after base-image refreshes.

This repo’s workflow sets **`ignore-unfixed: true`** on Trivy so alerts **without an available fix** are not reported to Code scanning (reduces noise; you still see fixable CVEs). After that change ships, re-run **Security scan**; remaining alerts should trend down. Use **Filters** on the Code scanning page by **Tool** (Trivy vs CodeQL) and **Severity**.

## Local Trivy

```bash
# Filesystem (install trivy CLI first); align with CI via --ignore-unfixed
trivy fs --severity HIGH,CRITICAL --ignore-unfixed .

# After building the decision-api image
docker build -f services/decision-api/Dockerfile -t tarka/decision-api:local .
trivy image --severity HIGH,CRITICAL --ignore-unfixed tarka/decision-api:local
```

## Policy

- **Critical** CVEs in default images: patch or document exception in the same release train.
- **Dependabot** PRs: run full CI; pay attention to `services/decision-api` and `integration-ingress` (broad dependency trees).

See [SECURITY.md](../../../SECURITY.md) for vulnerability reporting.
