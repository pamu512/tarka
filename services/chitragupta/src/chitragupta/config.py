import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    server_contract_version: str = "1.0.0"
    emitter_max_attempts: int = 3
    emitter_base_delay_seconds: float = 0.05


settings = Settings()
