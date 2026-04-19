from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    investigation_agent_url: str = Field(
        default="http://investigation-agent:8006",
        description="Base URL of investigation-agent (no trailing slash).",
    )
    investigation_agent_api_key: str = Field(
        default="",
        description="Optional x-api-key for investigation-agent.",
    )

    slack_signing_secret: str = Field(default="", description="Slack app signing secret (verifies Events API).")
    slack_bot_token: str = Field(
        default="",
        description="Bot token (xoxb-...) for chat.postMessage and optional thread history.",
    )

    teams_bridge_secret: str = Field(
        default="",
        description="Shared secret: incoming Teams/custom connector posts must send X-Bridge-Secret.",
    )

    lark_verification_token: str = Field(
        default="",
        description="Lark/Feishu event verification_token (matches event envelope token).",
    )
    lark_tenant_access_token: str = Field(
        default="",
        description="Lark tenant_access_token for open-apis im/v1/messages (post replies).",
    )

    default_tenant_id: str = Field(default="collab_default", max_length=128)
    default_case_id: str | None = Field(default=None, max_length=128)
    default_copilot_persona: Literal["investigation", "orchestrator"] = Field(
        default="investigation",
        description=(
            "Default persona for POST /v1/chat. Override per message with leading "
            "`!orch ` / `!orchestrator ` or `!inv ` / `!investigation ` on the last user line."
        ),
    )

    slack_skip_retry_background: bool = Field(
        default=True,
        description="If true, ignore X-Slack-Retry-Num>0 (avoid duplicate LLM runs on Slack timeout retries).",
    )
    slack_thread_under_mention: bool = Field(
        default=True,
        description="Reply in thread under the triggering message (uses message ts when not already in a thread).",
    )
    slack_max_thread_messages: int = Field(default=20, ge=2, le=50)

    bridge_rate_limit_per_minute: int = Field(
        default=0,
        ge=0,
        le=100_000,
        description="Per-key POST rate limit (Slack team_id, Teams/Lark client IP); 0 disables.",
    )
    bridge_web_fetch_enabled: bool = Field(
        default=True,
        description="If true, first https URL in last user message triggers SSRF-hardened fetch prepended to prompt.",
    )
    bridge_web_fetch_max_bytes: int = Field(default=500_000, ge=10_000, le=5_000_000)
    bridge_web_fetch_max_prefix_chars: int = Field(default=24_000, ge=2000, le=200_000)
    bridge_attachment_max_bytes: int = Field(
        default=4_000_000,
        ge=10_000,
        description="Per Slack file download cap.",
    )
    bridge_attachment_max_total_chars: int = Field(
        default=80_000,
        ge=2000,
        description="Total extracted attachment text appended to last user message.",
    )
