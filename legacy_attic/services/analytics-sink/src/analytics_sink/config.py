from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "fraud"
    nats_url: str = "nats://localhost:4222"
    stream_name: str = "FRAUD_DECISIONS"
    subject_prefix: str = "fraud.decisions"
    api_keys: str = ""


settings = Settings()
