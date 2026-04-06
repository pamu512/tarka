# Saarthi Pro — org analytics & multi-tenant admin (product spec)

> **Phase 3 product spec.** Describes **target capabilities**; implementation may ship incrementally in OSS and/or Pro. Not a commitment date.

## Goals

- **Org analytics:** aggregate copilot usage (turns, tools, errors, assurance refusals) and **optional** outcome hooks without exfiltrating case content.
- **Multi-tenant admin:** org-level config (profiles, feature flags, allowed models) for enterprises with many workspaces.

## Telemetry events (suggested schema)

Emit structured events to Customer’s **SIEM or data lake** (push) or expose **export API** (pull). PII minimization by default.

| Event `type` | Fields (illustrative) | Notes |
|--------------|------------------------|-------|
| `copilot.turn.completed` | `turn_id`, `tenant_id`, `analyst_id_hash`, `tool_invocation_count`, `assurance_mode`, `had_tool_error` | No raw prompt text. |
| `copilot.tool.error` | `tool_name`, `error_class`, `tenant_id` | Rate-limit per tenant. |
| `copilot.feedback.submitted` | `rating`, `turn_id`, `tenant_id` | If feedback feature on. |

**Opt-in (shipped in OSS agent):** set **`COPILOT_ANALYTICS_ENABLED=true`**, **`COPILOT_ANALYTICS_SINK=log`** (structured log line) or **`http`** + **`COPILOT_ANALYTICS_WEBHOOK_URL`**. Optional **`COPILOT_ANALYTICS_HMAC_SECRET`** adds **`analyst_id_hash`** on payloads. Events: **`copilot.turn.completed`** (each chat turn), **`copilot.feedback.submitted`** (feedback POST). Declared in **`GET /v1/health`** under `copilot_features.analytics_*`.

## Multi-tenant admin (future API sketch)

| Capability | Description |
|------------|-------------|
| **Tenant registry** | CRUD tenants; map IdP group → tenant. |
| **Profile override** | Set default `INTEGRATION_PROFILE_ID` per tenant. |
| **Feature flags** | Per-tenant `copilot_features` toggles aligned with `GET /v1/health`. |
| **Audit** | Admin action log (who changed which tenant config). |

Implementation options: separate **admin service**; or extend gateway with config store—**do not** put tenant secrets in agent env for all tenants.

## Boundaries

- **No** cross-tenant prompt or case data in analytics pipeline.
- **GDPR / retention:** Customer defines retention; Vendor-managed analytics follows DPA.

## Related

- [Economics & packaging appendix](saarthi-pro-economics-packaging-appendix.md)
- [Residency & VPC](saarthi-pro-residency-vpc-deployment.md)
