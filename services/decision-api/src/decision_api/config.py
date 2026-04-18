import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fraud:fraud@localhost:5432/fraud"
    redis_url: str = "redis://localhost:6379/0"
    feature_service_url: str = ""
    ml_scoring_url: str = ""
    graph_service_url: str = ""
    opa_url: str = ""
    rules_path: str = "./rules"
    api_keys: str = ""

    deny_threshold: float = 80.0
    review_threshold: float = 50.0
    score_blend_strategy: str = "average"  # "average", "max", "rules_only"

    nats_url: str = ""

    attestation_nonce_ttl: int = 300
    attestation_hmac_secret: str = ""

    default_region: str = "global"

    recaptcha_secret_key: str = ""
    hcaptcha_secret_key: str = ""
    turnstile_secret_key: str = ""

    list_store_backend: str = os.environ.get("LIST_STORE_BACKEND", "redis")
    list_store_api_url: str = os.environ.get("LIST_STORE_API_URL", "")
    list_store_api_key: str = os.environ.get("LIST_STORE_API_KEY", "")
    list_store_file_dir: str = os.environ.get("LIST_STORE_FILE_DIR", "./lists")

    consortium_enabled: bool = os.environ.get("CONSORTIUM_ENABLED", "true").lower() == "true"
    consortium_secret: str = os.environ.get("CONSORTIUM_SECRET", "")
    consortium_id: str = os.environ.get("CONSORTIUM_ID", "default")
    consortium_min_tenants: int = int(os.environ.get("CONSORTIUM_MIN_TENANTS", "2"))
    evidence_signing_secret: str = os.environ.get("EVIDENCE_SIGNING_SECRET", "")

    # Optional: enables POST /v1/internal/counters/replay (scratch Redis replay for parity ops)
    counter_replay_token: str = os.environ.get("COUNTER_REPLAY_TOKEN", "")

    # Optional: require HMAC on raw POST body for selected paths (see tls-pinning-and-signed-requests.md)
    request_signature_secret: str = os.environ.get("REQUEST_SIGNATURE_SECRET", "")
    request_signature_max_skew_seconds: int = int(os.environ.get("REQUEST_SIGNATURE_MAX_SKEW_SECONDS", "300"))

    # Challenge policy templates (JSON under {rules_path}/challenge_policies/)
    challenge_policy_default: str = os.environ.get("CHALLENGE_POLICY_DEFAULT", "default_v1")

    # Evaluation step controls (#32): timeouts (seconds), max attempts (1–5), optional REJECT (strict mode)
    eval_step_list_timeout_seconds: float = float(os.environ.get("EVAL_STEP_LIST_TIMEOUT_SECONDS", "0.8"))
    eval_step_list_max_attempts: int = int(os.environ.get("EVAL_STEP_LIST_MAX_ATTEMPTS", "2"))
    eval_step_feature_snapshot_timeout_seconds: float = float(os.environ.get("EVAL_STEP_FEATURE_SNAPSHOT_TIMEOUT_SECONDS", "2.5"))
    eval_step_feature_snapshot_max_attempts: int = int(os.environ.get("EVAL_STEP_FEATURE_SNAPSHOT_MAX_ATTEMPTS", "2"))
    eval_step_ml_timeout_seconds: float = float(os.environ.get("EVAL_STEP_ML_TIMEOUT_SECONDS", "2.5"))
    eval_step_ml_max_attempts: int = int(os.environ.get("EVAL_STEP_ML_MAX_ATTEMPTS", "2"))
    eval_step_graph_risk_timeout_seconds: float = float(os.environ.get("EVAL_STEP_GRAPH_RISK_TIMEOUT_SECONDS", "2.5"))
    eval_step_graph_risk_max_attempts: int = int(os.environ.get("EVAL_STEP_GRAPH_RISK_MAX_ATTEMPTS", "2"))
    eval_step_opa_timeout_seconds: float = float(os.environ.get("EVAL_STEP_OPA_TIMEOUT_SECONDS", "2.5"))
    eval_step_opa_max_attempts: int = int(os.environ.get("EVAL_STEP_OPA_MAX_ATTEMPTS", "2"))
    eval_step_graph_upsert_timeout_seconds: float = float(os.environ.get("EVAL_STEP_GRAPH_UPSERT_TIMEOUT_SECONDS", "8.0"))
    eval_step_graph_upsert_max_attempts: int = int(os.environ.get("EVAL_STEP_GRAPH_UPSERT_MAX_ATTEMPTS", "1"))

    # R2: outbound circuit breakers (consecutive failures before open, seconds until retry)
    circuit_graph_failure_threshold: int = int(os.environ.get("CIRCUIT_GRAPH_FAILURE_THRESHOLD", "5"))
    circuit_graph_recovery_seconds: float = float(os.environ.get("CIRCUIT_GRAPH_RECOVERY_SECONDS", "30"))
    circuit_feature_failure_threshold: int = int(os.environ.get("CIRCUIT_FEATURE_FAILURE_THRESHOLD", "5"))
    circuit_feature_recovery_seconds: float = float(os.environ.get("CIRCUIT_FEATURE_RECOVERY_SECONDS", "30"))
    circuit_ml_failure_threshold: int = int(os.environ.get("CIRCUIT_ML_FAILURE_THRESHOLD", "5"))
    circuit_ml_recovery_seconds: float = float(os.environ.get("CIRCUIT_ML_RECOVERY_SECONDS", "30"))
    circuit_opa_failure_threshold: int = int(os.environ.get("CIRCUIT_OPA_FAILURE_THRESHOLD", "5"))
    circuit_opa_recovery_seconds: float = float(os.environ.get("CIRCUIT_OPA_RECOVERY_SECONDS", "30"))
    circuit_list_failure_threshold: int = int(os.environ.get("CIRCUIT_LIST_FAILURE_THRESHOLD", "5"))
    circuit_list_recovery_seconds: float = float(os.environ.get("CIRCUIT_LIST_RECOVERY_SECONDS", "30"))

    # OSS #31: optional champion–challenger JSON rule evaluation (audit-only; production decision unchanged)
    policy_champion_challenger_enabled: bool = os.environ.get("POLICY_CHAMPION_CHALLENGER_ENABLED", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    policy_cohort_salt: str = os.environ.get("POLICY_COHORT_SALT", "policy_v1")
    # OSS #47 / #49: cohort salt + experiment id + graph checkpoint metadata key
    policy_experiment_id: str = os.environ.get("POLICY_EXPERIMENT_ID", "").strip()
    # OSS #49: metadata key for graph checkpoint profile (graph-service entity-risk)
    graph_checkpoint_metadata_key: str = os.environ.get("GRAPH_CHECKPOINT_METADATA_KEY", "graph_checkpoint")

    # N2: optional maker–checker for rule pack mutations (POST/PUT/DELETE rules APIs).
    # When set, clients must send matching X-Rule-Governance-Secret on mutating requests.
    rule_governance_secret: str = os.environ.get("RULE_GOVERNANCE_SECRET", "").strip()


settings = Settings()
