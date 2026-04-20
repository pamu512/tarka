# Enterprise Copilot — plugin embedding and governance controls

> **Integration and operations guide.** Covers the **system-agnostic plugin** handshake on **investigation-agent** (and optional **collaboration-chat-bridge** proxy), **maker–checker** enforcement on human review, **sensitive tool** gating, and **assurance metrics**. For Slack, Teams, and Lark ingress behavior, see [Investigation Copilot — collaboration chat (AWS / Azure)](investigation-collaboration-chat-aws-azure.md).

## Plugin session handshake (investigation-agent)

External case managers embed the copilot without giving browsers direct access to the agent:

1. **`POST /v1/plugin/session`** — issues a short-lived HMAC-signed session token (`token_type: plugin_session_v1`).
2. **`POST /v1/plugin/bootstrap`** — validates the token and returns scoped session context, governance metadata, and integration contract hints.

Responses include **`correlation_id`** in the JSON body and **`X-Correlation-Id`** on the HTTP response for tracing.

Configure a shared secret for signing:

| Variable | Purpose |
|----------|---------|
| `COPILOT_PLUGIN_SHARED_SECRET` | Required for token issuance and validation on the agent. |
| `COPILOT_PLUGIN_TOKEN_TTL_SECONDS` | Default TTL for issued tokens (bounds enforced in code). |

If the secret is unset, plugin endpoints are not usable for real sessions.

## Collaboration-chat-bridge proxy (optional)

When traffic should not reach the agent directly, the bridge exposes:

- `POST /v1/plugin/session`
- `POST /v1/plugin/bootstrap`

Callers authenticate with **`X-Bridge-Secret`** (see `BRIDGE_PLUGIN_SECRET` / `TEAMS_BRIDGE_SECRET` in the [collaboration chat guide](investigation-collaboration-chat-aws-azure.md)). The bridge forwards requests to the agent and emits **`bridge.plugin.audit`** structured logs.

## Maker–checker and sensitive tools

| Variable | Purpose |
|----------|---------|
| `COPILOT_MAKER_CHECKER_REQUIRED` | Default **true**. When enabled, `POST /v1/review/turn` rejects reviews where **`reviewer_id` equals the original turn author** (different human approves copilot output). |
| `COPILOT_REVIEWER_SECRET` | If set together with sensitive-tool policy, requests may need **`x-reviewer-secret`** to use gated tools. |
| `COPILOT_SENSITIVE_TOOLS` | Comma-separated tool names hidden unless reviewer secret matches (see agent settings). |

Review responses include **`maker_checker`** metadata describing whether the policy applied and whether enforcement triggered.

## Assurance metrics and governance

- **`GET /v1/review/metrics`** — aggregated review counts and rates for a tenant (windowed).
- **`GET /v1/governance`** — includes **`assurance_defaults`** (e.g. maker–checker requirement, sensitive-tool gate).

Use these for dashboards and periodic compliance reporting.

## Grafana / Loki (LogQL) — bridge audit events {: #grafana-loki-bridge-audit }

When the **collaboration-chat-bridge** fronts chat or plugin traffic, operators can alert on **`bridge.plugin.audit`** and **`bridge.ingress.audit`** JSON payloads embedded in log lines. Full troubleshooting patterns (two-phase Slack/Lark audits, correlation stitching) live in [Collaboration chat — Grafana / Loki](investigation-collaboration-chat-aws-azure.md#grafana-loki-logql).

### Label selector recipes

Pick **one** matcher that fits how logs reach Loki (adjust names to your cluster and scrape config):

| Deployment | Example selector |
|------------|------------------|
| Kubernetes (container name) | `{namespace="tarka", container="collaboration-chat-bridge"}` |
| Kubernetes (pod name regex) | `{namespace="tarka", pod=~"collaboration-chat-bridge.*"}` |
| Kubernetes (app label) | `{app="collaboration-chat-bridge"}` |
| Service / APM-style | `{service_name="collaboration-chat-bridge"}` |

The queries below use **`{namespace="tarka", container="collaboration-chat-bridge"}`** — replace the selector in every block if your labels differ.

Audit lines look like `bridge_ingress_audit {"event":"bridge.ingress.audit",...}` or `bridge_plugin_audit {...}` (prefix + compact JSON). Use the **`regexp` → `line_format` → `json`** pipeline to parse fields.

**Extract JSON payload (ingress):**

```logql
{namespace="tarka", container="collaboration-chat-bridge"}
  |= "bridge_ingress_audit"
  | regexp `bridge_ingress_audit (?P<payload>\{.*\})`
  | line_format "{{.payload}}"
  | json
```

**Ingress — upstream unavailable (`5xx`-class signal):**

```logql
sum(count_over_time(
  {namespace="tarka", container="collaboration-chat-bridge"}
    |= "bridge_ingress_audit"
    | regexp `bridge_ingress_audit (?P<payload>\{.*\})`
    | line_format "{{.payload}}"
    | json
    | event="bridge.ingress.audit"
    | outcome="unavailable"
    | status_class="5xx"
  [5m]
)) > 0
```

**Plugin — handshake failures:**

```logql
sum(count_over_time(
  {namespace="tarka", container="collaboration-chat-bridge"}
    |= "bridge_plugin_audit"
    | regexp `bridge_plugin_audit (?P<payload>\{.*\})`
    | line_format "{{.payload}}"
    | json
    | event="bridge.plugin.audit"
    | outcome=~"rejected|unavailable"
  [5m]
)) > 0
```

**Rate limits / auth:**

```logql
sum by (route) (count_over_time(
  {namespace="tarka", container="collaboration-chat-bridge"}
    |= "bridge_ingress_audit"
    | regexp `bridge_ingress_audit (?P<payload>\{.*\})`
    | line_format "{{.payload}}"
    | json
    | event="bridge.ingress.audit"
    | outcome=~"rate_limited|unauthorized"
  [15m]
)) > 0
```

If your pipeline already emits **only JSON** per line (no `bridge_*_audit` prefix), drop the `regexp` and `line_format` stages and filter with `| json` plus field matchers.

## Related

- OpenAPI: [`contracts/openapi/investigation-agent.yaml`](../../../contracts/openapi/investigation-agent.yaml)
- Bridge OpenAPI: [`contracts/openapi/collaboration-chat-bridge.yaml`](../../../contracts/openapi/collaboration-chat-bridge.yaml)
- [Investigation agent integration contract](investigation-agent-integration-contract.md)
- [Investigation Copilot — collaboration chat (AWS / Azure)](investigation-collaboration-chat-aws-azure.md)
