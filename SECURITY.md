# Security policy

Tarka is a fraud-detection platform; we take security reports seriously.

## Supported versions

Security fixes are applied on the default branch (`master` / `main`) and released per [RELEASE_SCHEDULE.md](RELEASE_SCHEDULE.md). Use tagged releases for production.

## Reporting a vulnerability

**Please do not** open a public GitHub issue for undisclosed security vulnerabilities.

1. Prefer **[GitHub private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)** (Security → Report a vulnerability) if enabled on the repository.
2. Otherwise contact the **repository maintainers** via the email or security policy shown on the GitHub org or repo homepage.
3. Include: description and impact, steps to reproduce (PoC if possible), affected components (e.g. decision-api, integration-ingress).
4. Allow up to **5 business days** for an initial response; we will coordinate disclosure and credit (if you wish) after a fix is available.

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

## Code of conduct

Community interaction is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
