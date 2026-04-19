# Investigation Copilot — collaboration chat (Slack, Teams, Lark) & cloud stand-alone

> **Operator guide.** Run the **collaboration-chat-bridge** next to **investigation-agent** so Slack, Microsoft Teams, and Lark/Feishu can call the same `/v1/chat` surface. Replies highlight **`answer_sections`** — including **INFERENCES**, **NEXT STEPS**, and (when present) **FACTS FROM TOOLS** / **UNKNOWNS** — when **`COPILOT_STRUCTURED_SECTIONS=true`** on the agent.

## Prerequisites

1. **Investigation agent** reachable from the bridge (same VPC / private link / mesh).
2. **LLM + upstream APIs** configured on the agent (`OPENAI_API_KEY`, `CASE_API_URL`, etc.) per your environment.
3. **Structured sections** (recommended for INFERENCES / NEXT STEPS in chat UIs):

   ```bash
   COPILOT_STRUCTURED_SECTIONS=true
   ```

   The system prompt then asks the model to emit `## INFERENCES` and `## NEXT STEPS`; the agent parses them into `answer_sections` on `POST /v1/chat` (see [`answer_structure.py`](../../../services/investigation-agent/src/investigation_agent/answer_structure.py)).

## Service: `collaboration-chat-bridge`

| Endpoint | Use |
|----------|-----|
| `GET /v1/health` | Liveness; shows which secrets are set. |
| `POST /v1/slack/events` | Slack Events API (URL verification + `event_callback`). Verifies `X-Slack-Signature`. Skips duplicate work when **`X-Slack-Retry-Num`** &gt; 0 if `SLACK_SKIP_RETRY_BACKGROUND=true` (default). |
| `POST /v1/teams/messages` | JSON ingress for Teams (Power Automate, API Management). Requires `X-Bridge-Secret`. Returns **`ok: true`** plus Adaptive Card on success; **`ok: false`** + error card if the agent is down (HTTP 200 for connector friendliness). |
| `POST /v1/teams/activity` | Bot Framework–shaped **`message`** activity (`type`, `text`, `from.id`). Same `X-Bridge-Secret`. |
| `POST /v1/plugin/session` | Bridge-proxied plugin/embed session issuance for external case managers. Requires `X-Bridge-Secret`; forwards to agent `/v1/plugin/session`. |
| `POST /v1/plugin/bootstrap` | Bridge-proxied plugin token bootstrap validation. Requires `X-Bridge-Secret`; forwards to agent `/v1/plugin/bootstrap`. |
| `POST /v1/lark/event` | Lark/Feishu event subscription (URL challenge + `im.message.receive_v1`). |

**Docker Compose** (profile **`collab`** or **`full`** / **`agent`**):

```bash
docker compose --profile collab up -d collaboration-chat-bridge investigation-agent
```

**Environment**

| Variable | Purpose |
|----------|---------|
| `INVESTIGATION_AGENT_URL` | e.g. `http://investigation-agent:8006` |
| `INVESTIGATION_AGENT_API_KEY` | Optional `x-api-key` for the agent |
| `SLACK_SIGNING_SECRET` | Slack app signing secret |
| `SLACK_BOT_TOKEN` | `xoxb-…` for `chat.postMessage` and `conversations.replies` (thread context) |
| `TEAMS_BRIDGE_SECRET` | Shared secret; callers send `X-Bridge-Secret` |
| `BRIDGE_PLUGIN_SECRET` | Optional dedicated secret for `/v1/plugin/*` (falls back to `TEAMS_BRIDGE_SECRET` when unset) |
| `LARK_VERIFICATION_TOKEN` | Matches Lark event `token` field |
| `LARK_TENANT_ACCESS_TOKEN` | Tenant token to call `im/v1/messages` for replies |
| `DEFAULT_TENANT_ID` / `DEFAULT_CASE_ID` | Default `tenant_id` / `case_id` for collab turns |
| `SLACK_SKIP_RETRY_BACKGROUND` | Default `true` — ignore Slack timeout retries so the LLM is not invoked twice |
| `BRIDGE_RATE_LIMIT_PER_MINUTE` | Optional cap on incoming POSTs (Slack per team, Teams per IP); `0` disables |
| `BRIDGE_WEB_FETCH_ENABLED` | Default `true` — prepend fetched text for first `https://` URL in user message (blocked private IPs) |
| `BRIDGE_ATTACHMENT_MAX_BYTES` / `BRIDGE_ATTACHMENT_MAX_TOTAL_CHARS` | Slack file download / inlined text caps |
| `SLACK_THREAD_UNDER_MENTION` | Default `true` — `chat.postMessage` uses a **thread** under the triggering message (`thread_ts` = message `ts` when not already in a thread) |
| `SLACK_MAX_THREAD_MESSAGES` | Default `20` — cap for `conversations.replies` (2–50) |

### Slack

1. Create a Slack app → **Event Subscriptions** → Request URL: `https://<host>/v1/slack/events`.
2. Subscribe to **`app_mention`** and optionally **`message.channels`** (noisy — start with mentions only).
3. **OAuth** → Bot token scopes: `chat:write`, `channels:history`, `groups:history`, `im:history`, `mpim:history`, `app_mentions:read`.
4. Install app to workspace; copy **Signing Secret** and **Bot User OAuth Token**.

The bridge **acks in &lt; 3s** and posts the copilot reply asynchronously via `chat.postMessage`. **Mentions** and **link** tokens are normalized before calling `/v1/chat`. If the agent errors, users still get a **Slack block** explaining the failure. **Mrkdwn** in model output is escaped for safe Block Kit rendering.

### Microsoft Teams

**Path A — Custom connector / Power Automate**

- HTTP POST to `https://<host>/v1/teams/messages` with header `X-Bridge-Secret: <TEAMS_BRIDGE_SECRET>` and body:

```json
{
  "text": "Analyst question or summary",
  "tenant_id": "acme",
  "analyst_id": "teams:user-id",
  "case_id": "optional-case-uuid",
  "thread_context": [
    {"role": "user", "content": "Earlier message"},
    {"role": "assistant", "content": "Earlier bot reply"}
  ]
}
```

Response includes `adaptive_card` (structured sections + **FactSet** `turn_id` on success) and `raw` agent JSON. On failure: `ok: false`, `error`, and an **Attention** Adaptive Card (still HTTP 200).

**Path B — Azure Bot Service**

- Register a Bot Channel + App Service / Container App that forwards **Activity** JSON to this endpoint (small adapter) or extend the bridge later with first-class Bot Framework JWT validation.

### External plugin / case-manager embedding

For system-agnostic embedding (external case manager UI + Tarka copilot backend):

1. Backend calls `POST /v1/plugin/session` with `tenant_id`, `analyst_id`, optional `case_id`.
2. Embed client receives token and calls `POST /v1/plugin/bootstrap`.
3. Bootstrap response returns scoped session context + governance + integration metadata.
4. Both endpoints return `correlation_id` and `X-Correlation-Id` for support/audit tracing.

This lets external UIs consume the same plugin session contract without direct network access to `investigation-agent`.

### Lark / Feishu

1. Create an app → enable **bot** + **IM** permissions → event subscription `im.message.receive_v1` (non-encrypted for simplest path).
2. Request URL: `https://<host>/v1/lark/event` — respond to URL verification challenge.
3. Set **Verification Token** → `LARK_VERIFICATION_TOKEN`.
4. Obtain **tenant_access_token** (OAuth) → `LARK_TENANT_ACCESS_TOKEN` for outbound `im/v1/messages`.

## Stand-alone on AWS

Typical pattern: **one task/service per container**, private subnets, **ALB** HTTPS → bridge + agent.

| Piece | Options |
|-------|---------|
| Compute | **ECS Fargate** or **EKS** (Deployment + Service) |
| Agent image | `services/investigation-agent/Dockerfile` |
| Bridge image | `services/collaboration-chat-bridge/Dockerfile` |
| Secrets | **Secrets Manager** → env (signing secrets, `OPENAI_API_KEY`, `API_KEYS`, Lark tokens) |
| Egress | NAT for OpenAI / Slack / Lark APIs; **VPC endpoints** where available |
| TLS | ACM certificate on ALB; optional **mTLS** to upstream case/decision APIs |

**Sizing (starting point):** bridge = 0.25 vCPU / 512 MB; agent = 0.5–1 vCPU / 1–2 GB depending on tool fan-out.

## Stand-alone on Azure

| Piece | Options |
|-------|---------|
| Compute | **Container Apps** or **App Service for Containers** |
| Networking | **VNet integration** + private DNS to your Tarka backends |
| Secrets | **Key Vault** references as env vars |
| Teams | Same HTTP bridge; place **API Management** in front for OAuth/rate limits |

## Security notes

- Treat **`TEAMS_BRIDGE_SECRET`** and Slack signing secret as **high sensitivity**.
- Lock **`API_KEYS`** and **`COPILOT_REQUIRE_INVESTIGATION_API_KEY=true`** on the agent in production.
- Collab channels may contain **PII**; align with DPIA and **data residency** (LLM region, logging).
- Slack/Lark thread text is sent to **`/v1/chat`** as `messages[]`; apply **retention** and **access controls** on logs.
- Plugin/embed endpoints emit structured audit events (`bridge.plugin.audit`) with action/outcome/status and correlation id.
- Non-plugin ingress (`/v1/slack/events`, `/v1/teams/messages`, `/v1/teams/activity`, `/v1/lark/event`) emits structured audit events (`bridge.ingress.audit`).
- Async channels (Slack/Lark) use a two-phase audit pattern: `accepted` on ingress, then a completion event with final `outcome` and optional `upstream_status` for agent failures.
- Correlate both phases using the same request `correlation_id` (`X-Request-Id`/`X-Correlation-Id` if supplied, otherwise bridge-generated).
- Bridge ingress and plugin responses include `X-Correlation-Id` so clients can stitch transport logs to audit events.

## Related

- OpenAPI contract: [`contracts/openapi/collaboration-chat-bridge.yaml`](../../../contracts/openapi/collaboration-chat-bridge.yaml)
- [Investigation agent integration contract](investigation-agent-integration-contract.md)
- [Investigation Agent Project](../projects/investigation-agent-project.md)
- [Investigation Copilot — intended use & data flows](investigation-agent-intended-use-and-data-flows.md)
