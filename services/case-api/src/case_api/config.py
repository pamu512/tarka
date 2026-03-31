import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fraud:fraud@localhost:5432/fraud_cases"
    graph_service_url: str = ""
    cors_origins: str = ""
    decision_api_url: str = os.environ.get("DECISION_API_URL", "http://localhost:8000")
    ml_scoring_url: str = os.environ.get("ML_SCORING_URL", "")
    evidence_signing_secret: str = os.environ.get("EVIDENCE_SIGNING_SECRET", "")


settings = Settings()
