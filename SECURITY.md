# Security policy

Tarka is a fraud-detection platform; we take security reports seriously.

## Supported versions

Security fixes are applied on **`master` only**. There is **no GA tag**. Do not run a draft tag in production.

## Reporting a vulnerability

**Please do not** open a public GitHub issue for undisclosed security vulnerabilities.

Private vulnerability reporting is **not enabled** on this repository (the public Security tab does not offer a working Report a vulnerability flow, and we cannot turn it on from here). Do not rely on a Report a vulnerability button.

Contact the **repository maintainers** via the email or contact method shown on the GitHub org or repo profile, if any is published.

Include: description and impact, steps to reproduce (PoC if possible), affected components (e.g. decision-api, integration-ingress).

Allow up to **5 business days** for an initial response; we will coordinate disclosure and credit (if you wish) after a fix is available.

## Automated scanning

- **Dependabot** opens dependency update PRs (see [.github/dependabot.yml](.github/dependabot.yml)).
- **Trivy** filesystem and container scans run on push/PR and weekly; results are uploaded to the **Security** tab as SARIF where GitHub Advanced Security or equivalent is available (see [.github/workflows/security-scan.yml](.github/workflows/security-scan.yml)).
- **CodeQL** may be enabled separately (see [.github/workflows/codeql.yml](.github/workflows/codeql.yml)).

See [docs/docs/guides/security-scanning.md](docs/docs/guides/security-scanning.md) for maintainer notes.

## Investigation Copilot (LLM)

The **investigation-agent** forwards chat, system instructions, optional platform-audit context, and **tool results** (cases, graph, decision audits) to the configured LLM endpoint. Operators should read **[Investigation Copilot — LLM data flow](docs/docs/guides/investigation-agent-llm-data-flow.md)** for subprocessors, tenant scoping, and the **`claims` / `reply`** response split before enabling in regulated environments.

## Scope and out of scope

**In scope:** RCE, authentication bypass, cross-tenant data access, insecure default credentials in shipped configs, dependency CVEs affecting default deployments.

**Out of scope:** Social engineering, denial-of-service without reproducible minimal load, issues requiring a compromised operator account, third-party Neo4j/cloud misconfiguration (see [LICENSE-DEPENDENCIES.md](LICENSE-DEPENDENCIES.md)).

This policy is not a SOC 2 (or other) attestation.

## Code of conduct

Community interaction is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
