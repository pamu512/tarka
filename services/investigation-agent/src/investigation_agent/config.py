from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    case_api_url: str = "http://localhost:8002"
    graph_service_url: str = ""
    decision_api_url: str = "http://localhost:8000"
    allowed_analysts: str = "*"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    upstream_api_key: str = ""


settings = Settings()
