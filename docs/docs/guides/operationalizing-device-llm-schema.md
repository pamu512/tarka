# Operationalizing Device Intel, LLM Failover, and Schema Registry

This guide turns the implemented capabilities into an operations checklist for rollout, validation, and ongoing monitoring.

## Scope

- Device intelligence scoring in `decision-api`
- Multi-provider LLM health/cost operations in `investigation-agent`
- Schema registry enforcement in `event-ingest`

## 1) Deployment Configuration

### Decision API

Enable edge signals (optional but recommended for production):

- `EDGE_SECURITY_SIGNALS_ENABLED=true`
- `EDGE_WAF_ACTION_HEADER=x-waf-action`
- `EDGE_BOT_SCORE_HEADER=x-bot-score`
- `EDGE_BOT_SCORE_BLOCK_THRESHOLD=25`
- `EDGE_BOT_SCORE_REVIEW_THRESHOLD=50`

Kubernetes probes:

- readiness: `GET /v1/ready`
- liveness: `GET /v1/health`

### Investigation Agent

Configure provider chain for failover:

- `LLM_PROVIDER=openai`
- `LLM_PROVIDER_FALLBACKS=anthropic,gemini,ollama`
- provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) as applicable

Kubernetes probes:

- readiness: `GET /v1/ready`
- liveness: `GET /v1/health`

### Event Ingest

Keep schema gate on for production:

- `INGEST_SCHEMA_REGISTRY_MODE=enforce`

Kubernetes probes:

- readiness: `GET /v1/ready`
- liveness: `GET /v1/health`

## 2) Runtime Validation Checklist

Run these checks from a trusted network segment with valid API keys.

### One-command smoke gate

```bash
python3 scripts/ci/operational_surface_smoke.py --api-key <key>
```

This validates:

- `decision-api` readiness (`/v1/ready`)
- `investigation-agent` readiness and LLM ops endpoints
- `event-ingest` readiness and schema registry status

### Decision API

```bash
curl -sS "http://localhost:8000/v1/ready"
curl -sS "http://localhost:8000/v1/device-intel/entity/<entity_id>?tenant_id=<tenant_id>" -H "x-api-key: <key>"
curl -sS "http://localhost:8000/v1/ops/edge-security-status" -H "x-api-key: <key>"
```

Expected outcomes:

- `/v1/ready` returns `"ready": true`
- device intel endpoint returns `summary.risk_score` and consortium/IP velocity fields when data exists
- edge security endpoint returns signal counters and configured thresholds

### Investigation Agent

```bash
curl -sS "http://localhost:8006/v1/ready" -H "x-api-key: <key>"
curl -sS "http://localhost:8006/v1/ops/llm-health" -H "x-api-key: <key>"
curl -sS "http://localhost:8006/v1/ops/llm-costs?hours=24" -H "x-api-key: <key>"
```

Expected outcomes:

- health output includes provider states and open circuits
- cost output shows per-provider totals, error counts, and latency

### Event Ingest

```bash
curl -sS "http://localhost:8007/v1/ready" -H "x-api-key: <key>"
curl -sS "http://localhost:8007/v1/schema-registry/status" -H "x-api-key: <key>"
curl -sS "http://localhost:8007/v1/ingest/stats" -H "x-api-key: <key>"
```

Expected outcomes:

- readiness is true when NATS and HTTP client are healthy (and Redis, if configured)
- schema registry status reports loaded versions and reject counters
- ingest stats expose `schema_registry_mode` and reject totals

## 3) Alerting Recommendations

Track and alert on:

- `decision-api` readiness failures and `device_intelligence:degraded` tags
- `investigation-agent` open LLM circuits or elevated provider error rates
- `event-ingest` schema reject growth (`ingest_schema_registry_validation_failed` and consumer schema reject counters)

## 4) Rollout Strategy

1. Deploy with probes enabled and schema mode set to `enforce`.
2. Validate readiness and ops endpoints in staging.
3. Replay known-good traffic and check for unexpected schema rejects.
4. Promote to production with on-call visibility for first 24 hours.
5. Keep a rollback path by preserving previous image tags and Helm values.

