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
    # Dashboards (moved from decision-api; prune plan v7 item 3.2)
    clickhouse_analytics_events_table: str = "fraud_decisions"
    nl_sql_allowed_tables: str = "fraud_decisions"
    redis_url: str = ""
    clickhouse_statement_timeout_ms: int = 30000


settings = Settings()
