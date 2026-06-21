import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fraud:fraud@localhost:5432/fraud_cases"
    graph_service_url: str = ""
    cors_origins: str = ""
    decision_api_url: str = os.environ.get("DECISION_API_URL", "http://localhost:8000")
    decision_api_key: str = Field(
        default="",
        description="Optional x-api-key for outbound GETs to decision-api (audit / explanation chain).",
    )
    ml_scoring_url: str = os.environ.get("ML_SCORING_URL", "")
    evidence_signing_secret: str = os.environ.get("EVIDENCE_SIGNING_SECRET", "")
    case_api_production_mode: bool = os.environ.get(
        "CASE_API_PRODUCTION_MODE", "false"
    ).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    dispute_provider_default_response_hours: int = Field(
        default=168,
        description="Default provider-response deadline from filing when none is supplied (hours).",
    )
    dispute_near_breach_ratio: float = Field(
        default=0.2,
        ge=0.05,
        le=0.95,
        description="Fraction of the filing→deadline window treated as near-breach tail.",
    )
    case_queue_routing_rules_json: str = ""

    # SAR FinCEN SFTP transport (BSA E-Filing). Worker uses these; empty host => FAILED (not left in SFTP_QUEUED).
    fincen_bsa_sftp_host: str = os.environ.get("FINCEN_BSA_SFTP_HOST", "").strip()
    fincen_bsa_sftp_port: int = int(os.environ.get("FINCEN_BSA_SFTP_PORT", "22"))
    fincen_bsa_sftp_user: str = os.environ.get("FINCEN_BSA_SFTP_USER", "").strip()
    fincen_bsa_sftp_password: str = os.environ.get("FINCEN_BSA_SFTP_PASSWORD", "").strip()
    fincen_bsa_sftp_remote_dir: str = (
        os.environ.get("FINCEN_BSA_SFTP_REMOTE_DIR", "/incoming").strip() or "/incoming"
    )

    # Messaging-driven SAR worker (tarka_core.MessageBroker).
    nats_url: str = os.environ.get("NATS_URL", "").strip()
    sar_transport_tick_seconds: float = float(os.environ.get("SAR_TRANSPORT_TICK_SECONDS", "30"))
    sar_transport_require_separate_ack: bool = os.environ.get(
        "SAR_TRANSPORT_REQUIRE_SEPARATE_ACK", "false"
    ).strip().lower() in ("1", "true", "yes", "on")


settings = Settings()
