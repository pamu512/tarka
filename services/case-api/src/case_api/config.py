from __future__ import annotations

import os
from typing import Mapping

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def production_lock_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Fail-closed case-api lock: explicit flag, Python production profile, or Helm prod.

    Compose production-hardening and Helm prod already set TARKA_DEPLOYMENT_PROFILE
    on core-api (case-api is the same process). CASE_API_PRODUCTION_MODE was the
    existing Python lock those overlays skipped — sqlite fallback and the
    default evidence HMAC still ran.
    """
    src = env if env is not None else os.environ
    if _truthy(src.get("CASE_API_PRODUCTION_MODE")):
        return True
    if (src.get("TARKA_DEPLOYMENT_PROFILE") or "").strip().lower() == "production":
        return True
    helm = (src.get("TARKA_HELM_ENVIRONMENT") or src.get("TARKA_ENVIRONMENT") or "").strip().lower()
    return helm == "prod"


_DEV_EVIDENCE_SIGNING_SECRET = "tarka-evidence-dev-secret"


def production_evidence_secret_errors(
    env: Mapping[str, str] | None = None,
    *,
    secret: str | None = None,
) -> list[str]:
    """Refuse empty or default evidence HMAC when the production lock is on."""
    if not production_lock_enabled(env):
        return []
    src = env if env is not None else os.environ
    raw = (secret if secret is not None else src.get("EVIDENCE_SIGNING_SECRET") or "").strip()
    if raw in ("", _DEV_EVIDENCE_SIGNING_SECRET):
        return [
            "EVIDENCE_SIGNING_SECRET must be explicitly set in production "
            "(CASE_API_PRODUCTION_MODE, TARKA_DEPLOYMENT_PROFILE=production, or Helm environment=prod)"
        ]
    return []


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
    # High-impact terminal statuses requiring a distinct second actor (missed-mark C1).
    case_maker_checker_statuses: str = os.environ.get(
        "CASE_MAKER_CHECKER_STATUSES", "resolved_fraud,sar_filed"
    )

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
