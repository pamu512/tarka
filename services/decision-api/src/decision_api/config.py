import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fraud:fraud@localhost:5432/fraud"
    redis_url: str = "redis://localhost:6379/0"
    feature_service_url: str = ""
    ml_scoring_url: str = ""
    graph_service_url: str = ""
    calibration_service_url: str = ""
    counter_service_url: str = ""
    location_service_url: str = ""
    scameter_enabled: bool = os.environ.get("SCAMETER_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    scameter_base_url: str = os.environ.get("SCAMETER_BASE_URL", "").strip()
    scameter_api_key: str = os.environ.get("SCAMETER_API_KEY", "").strip()
    external_signal_timeout_seconds: float = float(os.environ.get("EXTERNAL_SIGNAL_TIMEOUT_SECONDS", "1.8"))
    upstream_api_key: str = ""
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
    consortium_min_reports: int = int(os.environ.get("CONSORTIUM_MIN_REPORTS", "3"))
    consortium_score_trust_floor: float = float(os.environ.get("CONSORTIUM_SCORE_TRUST_FLOOR", "0.2"))
    consortium_score_max_delta: float = float(os.environ.get("CONSORTIUM_SCORE_MAX_DELTA", "35"))
    consortium_hash_scope: str = os.environ.get("CONSORTIUM_HASH_SCOPE", "consortium").strip().lower()
    evidence_signing_secret: str = os.environ.get("EVIDENCE_SIGNING_SECRET", "")
    decision_log_enabled: bool = os.environ.get("DECISION_LOG_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    decision_log_path: str = os.environ.get("DECISION_LOG_PATH", "./data/decision_logs/decision-log.jsonl")
    decision_log_warehouse_url: str = os.environ.get("DECISION_LOG_WAREHOUSE_URL", "")
    decision_log_warehouse_api_key: str = os.environ.get("DECISION_LOG_WAREHOUSE_API_KEY", "")

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
    eval_step_external_signal_max_attempts: int = int(os.environ.get("EVAL_STEP_EXTERNAL_SIGNAL_MAX_ATTEMPTS", "1"))

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
    circuit_calibration_failure_threshold: int = int(os.environ.get("CIRCUIT_CALIBRATION_FAILURE_THRESHOLD", "5"))
    circuit_calibration_recovery_seconds: float = float(os.environ.get("CIRCUIT_CALIBRATION_RECOVERY_SECONDS", "30"))
    circuit_counter_failure_threshold: int = int(os.environ.get("CIRCUIT_COUNTER_FAILURE_THRESHOLD", "5"))
    circuit_counter_recovery_seconds: float = float(os.environ.get("CIRCUIT_COUNTER_RECOVERY_SECONDS", "30"))
    circuit_location_failure_threshold: int = int(os.environ.get("CIRCUIT_LOCATION_FAILURE_THRESHOLD", "5"))
    circuit_location_recovery_seconds: float = float(os.environ.get("CIRCUIT_LOCATION_RECOVERY_SECONDS", "30"))
    circuit_external_failure_threshold: int = int(os.environ.get("CIRCUIT_EXTERNAL_FAILURE_THRESHOLD", "5"))
    circuit_external_recovery_seconds: float = float(os.environ.get("CIRCUIT_EXTERNAL_RECOVERY_SECONDS", "30"))

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

    # OSS #36 / deployment-profiles: analyst-visible evaluation posture (detection vs compliance UX).
    tarka_evaluation_mode: str = os.environ.get("TARKA_EVALUATION_MODE", "detection").strip().lower()
    # Optional explicit tier label: "community" | "pro" (empty = infer from configured URLs).
    tarka_deployment_tier: str = os.environ.get("TARKA_DEPLOYMENT_TIER", "").strip().lower()
    # Audience-level explainability surface: "minimal" (external-safe), "analyst", or "full".
    explainability_tier_default: str = os.environ.get("EXPLAINABILITY_TIER_DEFAULT", "analyst").strip().lower()
    # Epic X.4: tenant reliability hint for ops/analysts (invalid values treated as balanced).
    tarka_tenant_reliability_profile: str = os.environ.get("TARKA_TENANT_RELIABILITY_PROFILE", "balanced").strip().lower()

    # R3.2: when true, POST /v1/decisions/evaluate requires Idempotency-Key (or idempotency-key) header.
    evaluate_require_idempotency_key: bool = os.environ.get("TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY", "false").lower() in (
        "1",
        "true",
        "yes",
    )


settings = Settings()


def dependency_resilience_policy_table() -> dict[str, dict[str, float | int | str]]:
    """Single policy map for timeout/retry/circuit posture used by ops surfaces and docs."""
    return {
        "lists": {
            "timeout_seconds": settings.eval_step_list_timeout_seconds,
            "max_attempts": settings.eval_step_list_max_attempts,
            "circuit_failure_threshold": settings.circuit_list_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_list_recovery_seconds,
            "on_failure": "SKIP",
        },
        "graph_risk": {
            "timeout_seconds": settings.eval_step_graph_risk_timeout_seconds,
            "max_attempts": settings.eval_step_graph_risk_max_attempts,
            "circuit_failure_threshold": settings.circuit_graph_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_graph_recovery_seconds,
            "on_failure": "SKIP",
        },
        "feature_snapshot": {
            "timeout_seconds": settings.eval_step_feature_snapshot_timeout_seconds,
            "max_attempts": settings.eval_step_feature_snapshot_max_attempts,
            "circuit_failure_threshold": settings.circuit_feature_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_feature_recovery_seconds,
            "on_failure": "SKIP",
        },
        "ml_score": {
            "timeout_seconds": settings.eval_step_ml_timeout_seconds,
            "max_attempts": settings.eval_step_ml_max_attempts,
            "circuit_failure_threshold": settings.circuit_ml_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_ml_recovery_seconds,
            "on_failure": "SKIP",
        },
        "opa": {
            "timeout_seconds": settings.eval_step_opa_timeout_seconds,
            "max_attempts": settings.eval_step_opa_max_attempts,
            "circuit_failure_threshold": settings.circuit_opa_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_opa_recovery_seconds,
            "on_failure": "SKIP",
        },
        "counter_snapshot": {
            "timeout_seconds": settings.eval_step_feature_snapshot_timeout_seconds,
            "max_attempts": settings.eval_step_feature_snapshot_max_attempts,
            "circuit_failure_threshold": settings.circuit_counter_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_counter_recovery_seconds,
            "on_failure": "SKIP",
        },
        "location_eval": {
            "timeout_seconds": settings.eval_step_feature_snapshot_timeout_seconds,
            "max_attempts": settings.eval_step_feature_snapshot_max_attempts,
            "circuit_failure_threshold": settings.circuit_location_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_location_recovery_seconds,
            "on_failure": "SKIP",
        },
        "calibration": {
            "timeout_seconds": settings.eval_step_feature_snapshot_timeout_seconds,
            "max_attempts": settings.eval_step_feature_snapshot_max_attempts,
            "circuit_failure_threshold": settings.circuit_calibration_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_calibration_recovery_seconds,
            "on_failure": "SKIP",
        },
        "external_signals": {
            "timeout_seconds": settings.external_signal_timeout_seconds,
            "max_attempts": settings.eval_step_external_signal_max_attempts,
            "circuit_failure_threshold": settings.circuit_external_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_external_recovery_seconds,
            "on_failure": "SKIP",
        },
        "graph_upsert": {
            "timeout_seconds": settings.eval_step_graph_upsert_timeout_seconds,
            "max_attempts": settings.eval_step_graph_upsert_max_attempts,
            "circuit_failure_threshold": settings.circuit_graph_failure_threshold,
            "circuit_recovery_seconds": settings.circuit_graph_recovery_seconds,
            "on_failure": "SKIP",
        },
    }
