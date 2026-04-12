# collaboration-chat-bridge

HTTP bridge from **Slack Events API**, **Microsoft Teams** (`/v1/teams/messages` + Bot-shaped **`/v1/teams/activity`**), and **Lark/Feishu** events to **`investigation-agent` `POST /v1/chat`**.

- Surfaces **`answer_sections`** (INFERENCES, NEXT STEPS, optional FACTS / UNKNOWNS) with Slack mrkdwn escaping and threaded replies under mentions.
- **Skips Slack retries** (`X-Slack-Retry-Num`) by default to avoid duplicate LLM spend.
- **Copilot personas:** env **`DEFAULT_COPILOT_PERSONA`** (`investigation` \| `orchestrator`, default `investigation`). Override per user message with a leading command on the **last user** turn: **`!orch`**, **`!orchestrator`**, **`!inv`**, or **`!investigation`** (optional text after whitespace). **`POST /v1/teams/messages`** may set JSON **`persona`** to override env and message prefix.
- **Port:** `8009`

See [Investigation collaboration chat — AWS / Azure & platforms](../../../docs/docs/guides/investigation-collaboration-chat-aws-azure.md).
