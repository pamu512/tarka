import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fraud:fraud@localhost:5432/fraud"
    redis_url: str = "redis://localhost:6379/0"
    feature_service_url: str = ""
    ml_scoring_url: str = ""
    graph_service_url: str = ""
    opa_url: str = ""
    rules_path: str = "./rules"
    api_keys: str = ""

    deny_threshold: float = 80.0
    review_threshold: float = 50.0
    score_blend_strategy: str = "average"  # "average", "max", "rules_only"

    nats_url: str = ""

    attestation_nonce_ttl: int = 300
    attestation_hmac_secret: str = ""

    default_region: str = "global"

    recaptcha_secret_key: str = ""
    hcaptcha_secret_key: str = ""
    turnstile_secret_key: str = ""

    list_store_backend: str = os.environ.get("LIST_STORE_BACKEND", "redis")
    list_store_api_url: str = os.environ.get("LIST_STORE_API_URL", "")
    list_store_api_key: str = os.environ.get("LIST_STORE_API_KEY", "")
    list_store_file_dir: str = os.environ.get("LIST_STORE_FILE_DIR", "./lists")

    consortium_enabled: bool = os.environ.get("CONSORTIUM_ENABLED", "true").lower() == "true"
    consortium_secret: str = os.environ.get("CONSORTIUM_SECRET", "")
    consortium_id: str = os.environ.get("CONSORTIUM_ID", "default")
    consortium_min_tenants: int = int(os.environ.get("CONSORTIUM_MIN_TENANTS", "2"))
    evidence_signing_secret: str = os.environ.get("EVIDENCE_SIGNING_SECRET", "")

    # Optional: enables POST /v1/internal/counters/replay (scratch Redis replay for parity ops)
    counter_replay_token: str = os.environ.get("COUNTER_REPLAY_TOKEN", "")

    # Challenge policy templates (JSON under {rules_path}/challenge_policies/)
    challenge_policy_default: str = os.environ.get("CHALLENGE_POLICY_DEFAULT", "default_v1")


settings = Settings()
