from __future__ import annotations

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

    slack_skip_retry_background: bool = Field(
        default=True,
        description="If true, ignore X-Slack-Retry-Num>0 (avoid duplicate LLM runs on Slack timeout retries).",
    )
    slack_thread_under_mention: bool = Field(
        default=True,
        description="Reply in thread under the triggering message (uses message ts when not already in a thread).",
    )
    slack_max_thread_messages: int = Field(default=20, ge=2, le=50)
