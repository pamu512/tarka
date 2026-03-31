from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fraud:fraud@localhost:5432/fraud"
    api_keys: str = ""

    # OSINT API keys (all optional — sources without keys are skipped or use free tier)
    abuseipdb_key: str = ""
    greynoise_key: str = ""
    emailrep_key: str = ""
    numverify_key: str = ""
    ipinfo_token: str = ""


settings = Settings()
