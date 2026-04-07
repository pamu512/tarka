# collaboration-chat-bridge

HTTP bridge from **Slack Events API**, **Microsoft Teams** (`/v1/teams/messages` + Bot-shaped **`/v1/teams/activity`**), and **Lark/Feishu** events to **`investigation-agent` `POST /v1/chat`**.

- Surfaces **`answer_sections`** (INFERENCES, NEXT STEPS, optional FACTS / UNKNOWNS) with Slack mrkdwn escaping and threaded replies under mentions.
- **Skips Slack retries** (`X-Slack-Retry-Num`) by default to avoid duplicate LLM spend.
- **Port:** `8009`

See [Investigation collaboration chat — AWS / Azure & platforms](../../../docs/docs/guides/investigation-collaboration-chat-aws-azure.md).
