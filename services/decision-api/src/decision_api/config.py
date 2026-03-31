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


settings = Settings()
