from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    decision_api_url: str = Field(
        default="http://localhost:8000/decisions",
        validation_alias=AliasChoices("GATEWAY_DECISION_API_URL", "DECISION_API_URL"),
    )
    case_api_url: str = Field(
        default="http://localhost:8000/cases",
        validation_alias=AliasChoices("GATEWAY_CASE_API_URL", "CASE_API_URL"),
    )
    graph_service_url: str = Field(
        default="http://localhost:8001",
        validation_alias=AliasChoices("GATEWAY_GRAPH_SERVICE_URL", "GRAPH_SERVICE_URL"),
    )

    api_keys: str = Field(default="", validation_alias=AliasChoices("GATEWAY_API_KEYS", "API_KEYS"))
    allow_insecure_no_auth: bool = Field(
        default=False,
        validation_alias=AliasChoices("GATEWAY_ALLOW_INSECURE_NO_AUTH", "ALLOW_INSECURE_NO_AUTH"),
    )

    http_timeout: float = Field(default=10.0, validation_alias="GATEWAY_HTTP_TIMEOUT")
    http_connect_timeout: float = Field(default=3.0, validation_alias="GATEWAY_HTTP_CONNECT_TIMEOUT")
    http_max_connections: int = Field(default=200, validation_alias="GATEWAY_HTTP_MAX_CONNECTIONS")
    http_max_keepalive: int = Field(default=40, validation_alias="GATEWAY_HTTP_MAX_KEEPALIVE")


settings = Settings()
