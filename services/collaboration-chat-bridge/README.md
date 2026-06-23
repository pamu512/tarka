# collaboration-chat-bridge

HTTP bridge from **Slack Events API**, **Microsoft Teams** (`/v1/teams/messages` + Bot-shaped **`/v1/teams/activity`**), and **Lark/Feishu** events to **`investigation-agent` `POST /v1/chat`**.

- Surfaces **`answer_sections`** (INFERENCES, NEXT STEPS, optional FACTS / UNKNOWNS) with Slack mrkdwn escaping and threaded replies under mentions.
- **Skips Slack retries** (`X-Slack-Retry-Num`) by default to avoid duplicate LLM spend.
- **Copilot personas:** env **`DEFAULT_COPILOT_PERSONA`** (`investigation` \| `orchestrator`, default `investigation`). Override per user message with a leading command on the **last user** turn: **`!orch`**, **`!orchestrator`**, **`!inv`**, or **`!investigation`** (optional text after whitespace). **`POST /v1/teams/messages`** may set JSON **`persona`** to override env and message prefix.
- **Workflows (Skuld-style directives)** on the **last user** message: **`!wf <workflow_id>`**, **`!wfp key=value`** (space-separated pairs), **`!style standard|concise|detailed|executive|tutorial`** (maps to common `workflow_params` such as `audience` / `report_label`). Teams JSON may also set **`workflow_id`**, **`workflow_params`**, **`playbook_id`**, **`batch_id`** (explicit fields override `!wf` / merge into `!wfp`).
- **Slack file attachments:** files on the triggering message are downloaded with the bot token; text, CSV, and PDF (via **pypdf**) are appended to the last user turn (size-capped).
- **Optional URL context:** first `https://` URL in the last user message can be fetched (SSRF-hardened) and prepended to the prompt — **`BRIDGE_WEB_FETCH_ENABLED`** (default true).
- **Ingress rate limit:** **`BRIDGE_RATE_LIMIT_PER_MINUTE`** (0 = off) — per Slack `team_id`, per Teams client IP.
- **Port:** `8009`

See [Investigation collaboration chat — AWS / Azure & platforms](../../../docs/docs/guides/investigation-collaboration-chat-aws-azure.md).
