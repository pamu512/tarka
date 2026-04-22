# Production security rollout checklist

Use this guide when promoting **auth, tenant binding, Copilot, collaboration bridge, ingest idempotency, and decision-log** hardening from staging to production. It complements [Deployment](./deployment.md), [Managed services and secrets contract](./deployment-managed-services.md), and [Cloud release readiness](./deployment-release-readiness.md).

---

## Preconditions

- **API gateway** (or equivalent) can inject trusted headers and enforce TLS for all public paths.
- **Kubernetes Secrets** (or External Secrets) exist for shared material; nothing sensitive is committed in Git.
- **Staging** has exercised: `POST /v1/decisions/evaluate`, `POST /v1/events`, Copilot `POST /v1/chat`, Teams bridge `POST /v1/teams/messages`, and any **WebSocket** dashboards you use.

---

## New and changed controls (reference)

| Variable / control | Where it applies | Purpose |
| --- | --- | --- |
| `ALLOW_INSECURE_NO_AUTH` | Services using `auth_rbac` / shared auth patterns | Must be **false** in production; when true with empty `API_KEYS`, anonymous access is possible. |
| `API_KEYS` | All services that validate `X-API-Key` | Non-empty in production; comma-separated rotation window supported (re-read on each request in shared `auth.py`). |
| `TENANT_BINDING_REQUIRED` | decision-api, case-api, integration-ingress (middleware); graph-service, analytics-sink (API-key paths) | When **true**, requests that carry a `tenant_id` (query, path, or JSON body) must match the caller’s tenant scope. |
| `API_KEY_TENANT_MAP` | Same as above | JSON object: API key string → tenant id or list of tenant ids. Use `"*"` only for dedicated break-glass keys. Example: `{"svc-key-1":["tenant_a","tenant_b"]}`. |
| `UPSTREAM_API_KEY` | event-ingest → decision-api | Must match a key accepted by **decision-api** when `ALLOW_INSECURE_NO_AUTH=false`. If unset, event-ingest falls back to the first entry in its own `API_KEYS` (set explicitly to avoid ambiguity). |
| `INGEST_REQUIRE_IDEMPOTENCY_KEY` | event-ingest | When **true**, `POST /v1/events` requires an idempotency key (see [ingest replay onboarding](./ingest-replay-onboarding.md)). |
| `TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY` | decision-api | When **true**, `POST /v1/decisions/evaluate` requires `Idempotency-Key`. |
| `DECISION_LOG_INCLUDE_PAYLOAD_SNAPSHOT` | decision-api | Default **false**: omits full payload in JSONL; when **true**, payload is still **redacted** for common secret-like keys. |
| `COPILOT_PRODUCTION_MODE`, `COPILOT_REQUIRE_INVESTIGATION_API_KEY`, `ALLOWED_ANALYSTS`, `COPILOT_INJECTION_POLICY` | investigation-agent | Fail-fast and abuse controls; see `deploy/docker-compose.production-hardening.yml`. |
| `COPILOT_TRUSTED_SCOPE_HEADERS_REQUIRED` | investigation-agent | When **true**, `POST /v1/chat` requires **`X-Tenant-Id`** and **`X-Analyst-Id`**; body `tenant_id` / `analyst_id` are **overridden** by those headers. |
| `BRIDGE_TRUSTED_SCOPE_HEADERS_REQUIRED` | collaboration-chat-bridge | When **true**, Teams ingress requires **`X-Tenant-Id`** and **`X-Analyst-Id`**; body tenant/analyst are not trusted alone. |
| `TEAMS_ALLOWED_TENANT_IDS` | collaboration-chat-bridge | Optional comma-separated allowlist of resolved tenant ids after header/body resolution. |
| `CASE_API_PRODUCTION_MODE` | case-api | When **true**, `EVIDENCE_SIGNING_SECRET` must be set to a non-default value at startup. |

**Compose overlay:** `deploy/docker-compose.production-hardening.yml` turns on several of the above for a reference “full” profile. Merge it only after secrets and gateway headers are ready:

`docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.production-hardening.yml ...`

**Helm:** set `global.appSecretsName` to a Secret that contains at least `API_KEYS`; optional keys include `API_KEY_TENANT_MAP`, `POSTGRES_PASSWORD`, `EVIDENCE_SIGNING_SECRET`, etc. (see templates under `deploy/helm/fraud-stack/templates/`).

---

## Compatibility toggles (staged)

Use these **in order**; each step should pass smoke tests before the next.

1. **Secrets only** — Deploy with new Secret objects but **unchanged** feature flags (`TENANT_BINDING_REQUIRED=false`, etc.). Fix any mount or key name mismatches.
2. **Tenant map without enforcement** — Set `API_KEY_TENANT_MAP` correctly while `TENANT_BINDING_REQUIRED=false`. Validate mapping JSON and client behavior; no 403s yet.
3. **Tenant binding on** — Set `TENANT_BINDING_REQUIRED=true` on one service (e.g. decision-api), then expand to case-api, graph-service, analytics-sink, integration-ingress.
4. **Ingest → decision auth** — Set `UPSTREAM_API_KEY` on event-ingest to a key that decision-api accepts; verify NATS consumer processes messages (no 401 on evaluate).
5. **Idempotency** — Enable `INGEST_REQUIRE_IDEMPOTENCY_KEY` and/or `TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY` after all producers send keys.
6. **WebSockets** — Update dashboards to pass **`tenant_id`** query parameter and **`X-API-Key`**; confirm only the intended tenant receives events.
7. **Copilot trusted headers** — Configure gateway to set `X-Tenant-Id` / `X-Analyst-Id` from SSO, then set `COPILOT_TRUSTED_SCOPE_HEADERS_REQUIRED=true` (and `COPILOT_PRODUCTION_MODE=true` per your policy).
8. **Teams bridge** — Set `BRIDGE_TRUSTED_SCOPE_HEADERS_REQUIRED=true` and optionally `TEAMS_ALLOWED_TENANT_IDS` after Power Automate (or proxy) sends the headers.
9. **Decision log minimization** — Keep `DECISION_LOG_INCLUDE_PAYLOAD_SNAPSHOT=false` unless auditors require payloads; warehouse sink still receives the same record shape.
10. **Case API production** — Set `CASE_API_PRODUCTION_MODE=true` only when `EVIDENCE_SIGNING_SECRET` is provisioned.

---

## Recommended cutover order

```text
Secrets + API_KEYS
  → UPSTREAM_API_KEY (event-ingest ↔ decision-api)
  → TENANT_BINDING_REQUIRED + API_KEY_TENANT_MAP
  → Idempotency flags (ingest, then evaluate)
  → WebSocket clients
  → Copilot production + trusted headers
  → Bridge trusted headers + tenant allowlist
  → Decision log / case signing production flags
```

---

## Client and integration migration notes

- **REST callers:** Ensure every mutating or tenant-scoped call includes a consistent `tenant_id` (query, path, or body) matching the key’s map when binding is on.
- **WebSockets:** `GET /v1/decisions/ws` and `GET /v1/cases/ws` require `?tenant_id=...` and a valid `X-API-Key` when keys are configured.
- **Investigation Copilot:** With `COPILOT_TRUSTED_SCOPE_HEADERS_REQUIRED=true`, the gateway must send **`X-Tenant-Id`** and **`X-Analyst-Id`**; body fields are overwritten server-side.
- **Teams bridge:** With `BRIDGE_TRUSTED_SCOPE_HEADERS_REQUIRED=true`, the connector must send the same two headers; configure `TEAMS_ALLOWED_TENANT_IDS` if only a fixed set of tenants may use the bridge.

---

## Rollback (fast)

| Symptom | Rollback action |
| --- | --- |
| 403 tenant scope | Set `TENANT_BINDING_REQUIRED=false` temporarily; fix `API_KEY_TENANT_MAP`; re-enable. |
| Ingest stuck / evaluate 401 | Verify `UPSTREAM_API_KEY` and decision-api `API_KEYS`; align or revert ingest image env. |
| Copilot/chat 400 on headers | Disable `COPILOT_TRUSTED_SCOPE_HEADERS_REQUIRED` until gateway injects headers. |
| Teams bridge rejections | Disable `BRIDGE_TRUSTED_SCOPE_HEADERS_REQUIRED` or fix header mapping. |
| Strict idempotency breaks clients | Set `INGEST_REQUIRE_IDEMPOTENCY_KEY` / `TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY` to **false** until clients comply. |

**Emergency dev-only (never on internet-facing):** `ALLOW_INSECURE_NO_AUTH=true` only as a last resort on isolated networks; remove immediately after mitigation.

---

## Post-cutover validation

- [ ] All services report **200** on `/v1/health` with production env.
- [ ] Evaluate and ingest succeed end-to-end with **idempotency** when required flags are on.
- [ ] Cross-tenant negative test: key mapped to `tenant_a` receives **403** on `tenant_b` data.
- [ ] WebSocket subscriber only receives events for **subscribed** `tenant_id`.
- [ ] Prometheus: no sustained burn on `TarkaDecisionApiFallbackRateElevated` or circuit-open alerts ([slo-burn rules](../../../deploy/observability/prometheus-rules/slo-burn.yml)).
- [ ] Decision log line count grows without unexpected payload growth when snapshots are omitted.

---

## Related documentation

- [deployment-managed-services.md](./deployment-managed-services.md) — `API_KEY_TENANT_MAP` and `global.appSecretsName`
- [deployment-release-readiness.md](./deployment-release-readiness.md) — release gate checklist
- [investigation-agent-llm-data-flow.md](./investigation-agent-llm-data-flow.md) — Copilot data boundary
- [ingest-replay-onboarding.md](./ingest-replay-onboarding.md) — ingest idempotency semantics
