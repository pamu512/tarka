"""Runtime settings for data-platform service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_keys: str = ""
    allow_insecure_no_auth: bool = False

    redis_url: str = "redis://redis:6379/0"
    redis_stream: str = "tarka:events"
    redis_consumer_group: str = "data-platform"
    redis_consumer_name: str = "worker-1"
    redis_block_ms: int = 1000
    redis_batch_size: int = 100

    database_url: str = "postgresql://fraud:fraud@postgres:5432/fraud"
    analytics_backend: str = "postgres"

    enable_consumer: bool = True


settings = Settings()
