# Regional AI governance builds (US / EU+UK / Global)

Tarka supports **three deployment profiles** for **AI governance alignment**: **United States**, **EU / UK**, and **Global**. They adjust:

- **Investigation Copilot** system prompt (regional expectations for human oversight, data use, and documentation).
- **Optional defaults** (e.g. in-memory **batch upload TTL**, **injection policy**) via environment variables.
- **UI** build-time label (`VITE_AI_GOVERNANCE_PROFILE`) plus runtime **`GET /v1/governance`** for verification.

**This documentation is not legal advice.** Map controls to your **use case**, **sector**, **jurisdiction**, and **contracts** with qualified counsel and your DPO.

## Profiles at a glance

| Build | `AI_GOVERNANCE_PROFILE` | Emphasis |
|-------|-------------------------|----------|
| **US** | `us` | NIST AI RMF–style framing; fair lending / UDAAP-style fairness awareness; human accountability for consumer-impacting decisions |
| **EU / UK** | `eu_uk` | GDPR + EU AI Act–oriented *operational* language; data minimization; human oversight; shorter default batch retention |
| **Global** | `global` | ISO/IEC 42001–style themes; strongest-common baseline; local law still applies |

Aliases such as `usa`, `eea`, `gdpr`, `uk` normalize to the closest profile (see `services/investigation-agent/.../governance.py`).

## How to deploy

### Docker Compose

Use the profile directory **[deploy/profiles/ai-governance](../../../deploy/profiles/ai-governance/README.md)**:

- **Overrides:** `docker-compose.override-us.yml`, `docker-compose.override-eu-uk.yml`, `docker-compose.override-global.yml`
- **Env snippets:** `us.env`, `eu-uk.env`, `global.env`

Base **[deploy/docker-compose.yml](../../../deploy/docker-compose.yml)** passes through `AI_GOVERNANCE_PROFILE`, `BATCH_TTL_SECONDS`, `COPILOT_INJECTION_POLICY`, and frontend **`VITE_AI_GOVERNANCE_PROFILE`** from your shell or `deploy/.env`.

### Helm

Set **`investigationAgent.aiGovernanceProfile`**, optional **`batchTtlSeconds`**, and **`extraEnv`** (e.g. `COPILOT_INJECTION_POLICY`).

Example fragments: **[deploy/profiles/ai-governance/helm/](../../../deploy/profiles/ai-governance/helm/)**.

Pre-built **frontend images** should be built with the matching **`VITE_AI_GOVERNANCE_PROFILE`** build arg (see **[frontend/Dockerfile](../../../frontend/Dockerfile)**).

### Local development

```bash
export AI_GOVERNANCE_PROFILE=eu_uk
export BATCH_TTL_SECONDS=3600
export VITE_AI_GOVERNANCE_PROFILE=eu_uk
```

Run **investigation-agent** and **frontend** as usual.

## API surfaces

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/health` | `ai_governance_profile`, `ai_governance_label` |
| `GET /v1/governance` | Profile, label, illustrative **reference list**, `batch_ttl_seconds`, disclaimer |

OpenAPI: **[contracts/openapi/investigation-agent.yaml](../../../contracts/openapi/investigation-agent.yaml)**.

## Reference lists (illustrative)

The API returns short lists (e.g. NIST AI RMF, EU AI Act, GDPR, ICO). They are **starting points for RFPs and control mapping**, not an assertion that the software is certified or compliant.

## Related

- [Investigation Agent Project](../projects/investigation-agent-project.md)
- [Security scanning](security-scanning.md)
- [Saarthi Pro vs OSS](saarthi-pro-vs-oss.md) (commercial packaging vs self-hosted OSS)
