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

    # Vault KMS settings
    integration_vault_key: str = "tarka-integration-vault-dev-key"
    kms_provider: str = "local"  # local | aws | gcp | azure
    kms_active_key_id: str = "v1"
    kms_keyring_json: str = ""  # optional JSON map {"v1":"secret","v2":"secret2"}
    kms_rotation_enabled: bool = False
    kms_rotation_interval_seconds: int = 86400
    kms_startup_self_check: bool = False
    aws_kms_region: str = "us-east-1"
    aws_kms_endpoint_url: str = ""
    gcp_kms_key_resource: str = ""
    azure_key_vault_url: str = ""
    azure_kms_key_name: str = ""
    azure_kms_credential_mode: str = "default"  # default | client_secret


settings = Settings()
