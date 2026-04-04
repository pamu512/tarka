# Security scanning (maintainers)

## Where results appear

| Mechanism | Workflow | Output |
|-----------|-----------|--------|
| **Trivy** (filesystem + decision-api image) | [.github/workflows/security-scan.yml](../../../.github/workflows/security-scan.yml) | SARIF uploaded to **GitHub → Security → Code scanning** (when available for the repo). Table output in job logs. |
| **Dependabot** | [.github/dependabot.yml](../../../.github/dependabot.yml) | **Pull requests** grouped by ecosystem; review + CI before merge. |
| **CodeQL** | [.github/workflows/codeql.yml](../../../.github/workflows/codeql.yml) | Static analysis alerts (if enabled). |

Forks and some plan tiers may not show SARIF uploads; logs still contain Trivy tables.

## Local Trivy

```bash
# Filesystem (install trivy CLI first)
trivy fs --severity HIGH,CRITICAL .

# After building the decision-api image
docker build -f services/decision-api/Dockerfile -t tarka/decision-api:local .
trivy image --severity HIGH,CRITICAL tarka/decision-api:local
```

## Policy

- **Critical** CVEs in default images: patch or document exception in the same release train.
- **Dependabot** PRs: run full CI; pay attention to `services/decision-api` and `integration-ingress` (broad dependency trees).

See [SECURITY.md](../../../SECURITY.md) for vulnerability reporting.
