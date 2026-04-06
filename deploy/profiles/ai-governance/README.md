# Regional AI governance builds (US / EU+UK / Global)

Tarka aligns the **Investigation Copilot** (and related env defaults) with common **AI governance** expectations by region. This is **not** legal advice; each customer must validate against counsel, DPAs, and sector rules.

## Profiles

| Profile | `AI_GOVERNANCE_PROFILE` | Typical use |
|--------|-------------------------|-------------|
| **United States** | `us` | NIST AI RMF–style framing, fair-lending / UDAAP awareness, human accountability for consumer impact |
| **EU / UK** | `eu_uk` | GDPR + EU AI Act–oriented prompts, data minimization, human oversight, shorter default batch TTL |
| **Global** | `global` | ISO 42001–style baseline, local law still applies |

Aliases accepted by the agent: `usa`, `eea`, `gdpr`, `intl`, etc. (see `governance.normalize_governance_profile`).

## Docker Compose

From repo root, layer an override **after** the base compose file:

```bash
# United States build
docker compose -f deploy/docker-compose.yml -f deploy/profiles/ai-governance/docker-compose.override-us.yml --profile full up -d --build

# EU / UK build
docker compose -f deploy/docker-compose.yml -f deploy/profiles/ai-governance/docker-compose.override-eu-uk.yml --profile full up -d --build

# Global (explicit; same as omitting override if defaults unchanged)
docker compose -f deploy/docker-compose.yml -f deploy/profiles/ai-governance/docker-compose.override-global.yml --profile full up -d --build
```

Overrides set:

- **`investigation-agent`**: `AI_GOVERNANCE_PROFILE`, and for **EU/UK** a shorter **`BATCH_TTL_SECONDS`** (1h) for in-memory batch uploads.
- **`frontend`**: **`VITE_AI_GOVERNANCE_PROFILE`** build arg so the UI shows the matching governance strip.

## Env-only (no override file)

Copy variables from `us.env`, `eu-uk.env`, or `global.env` into `deploy/.env` or your secret store.

## Helm

Use `values` overrides:

```bash
helm upgrade --install tarka ./deploy/helm/fraud-stack -f deploy/profiles/ai-governance/helm/values-us.yaml
```

See `helm/*.yaml` in this directory.

## API

- **`GET /v1/health`** — includes `ai_governance_profile` and `ai_governance_label`.
- **`GET /v1/governance`** — profile, human-readable label, reference list, `batch_ttl_seconds`, disclaimer.

Full narrative: **[docs/docs/guides/ai-governance-regional-builds.md](../../../docs/docs/guides/ai-governance-regional-builds.md)**.
