from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    nats_url: str = "nats://localhost:4222"
    decision_api_url: str = "http://localhost:8000"
    stream_name: str = "FRAUD_EVENTS"
    subject_prefix: str = "fraud.events"
    batch_flush_ms: int = 100
    max_batch_size: int = 256
    api_keys: str = ""


settings = Settings()
