from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    decision_api_url: str = "http://localhost:8000"
    case_api_url: str = "http://localhost:8002"
    graph_service_url: str = "http://localhost:8001"

    api_keys: str = ""
    allow_insecure_no_auth: bool = False

    http_timeout: float = 10.0
    http_connect_timeout: float = 3.0
    http_max_connections: int = 200
    http_max_keepalive: int = 40

    model_config = {"env_prefix": "GATEWAY_"}


settings = Settings()
