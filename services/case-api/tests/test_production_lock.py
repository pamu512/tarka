"""Case-api production lock: sqlite fallback and default evidence HMAC."""

from pathlib import Path

from case_api.config import (
    _DEV_EVIDENCE_SIGNING_SECRET,
    production_evidence_secret_errors,
    production_lock_enabled,
)


def test_production_lock_off_by_default():
    assert production_lock_enabled({}) is False


def test_production_lock_from_explicit_flag():
    assert production_lock_enabled({"CASE_API_PRODUCTION_MODE": "true"})
    assert production_lock_enabled({"CASE_API_PRODUCTION_MODE": "1"})
    assert not production_lock_enabled({"CASE_API_PRODUCTION_MODE": "false"})


def test_production_lock_from_deployment_profile_or_helm():
    """Overlay leftover: Helm/compose set the profile on core-api; case-api ignored it."""
    assert production_lock_enabled({"TARKA_DEPLOYMENT_PROFILE": "production"})
    assert production_lock_enabled({"TARKA_HELM_ENVIRONMENT": "prod"})
    assert production_lock_enabled({"TARKA_ENVIRONMENT": "prod"})
    assert not production_lock_enabled({"TARKA_DEPLOYMENT_PROFILE": "dev"})
    assert not production_lock_enabled({"TARKA_HELM_ENVIRONMENT": "dev"})


def test_compose_production_hardening_sets_case_api_production_mode():
    overlay = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "deploy"
        / "docker-compose.production-hardening.yml"
    ).read_text(encoding="utf-8")
    assert 'CASE_API_PRODUCTION_MODE: "true"' in overlay
    assert (
        "core-api:\n    environment:\n      TARKA_DEPLOYMENT_PROFILE: production\n"
        '      CASE_API_PRODUCTION_MODE: "true"'
    ) in overlay


def test_empty_evidence_secret_fails_in_production():
    errs = production_evidence_secret_errors(
        {"CASE_API_PRODUCTION_MODE": "true"},
        secret="",
    )
    assert any("EVIDENCE_SIGNING_SECRET" in e for e in errs)


def test_dev_evidence_hmac_fails_under_deployment_profile():
    errs = production_evidence_secret_errors(
        {"TARKA_DEPLOYMENT_PROFILE": "production"},
        secret=_DEV_EVIDENCE_SIGNING_SECRET,
    )
    assert any("EVIDENCE_SIGNING_SECRET" in e for e in errs)


def test_resolved_evidence_secret_passes_in_production():
    assert (
        production_evidence_secret_errors(
            {"TARKA_HELM_ENVIRONMENT": "prod"},
            secret="prod-evidence-hmac",
        )
        == []
    )


def test_evidence_secret_not_required_outside_production():
    assert production_evidence_secret_errors({}, secret="") == []


def test_db_refuses_sqlite_fallback_under_production_lock():
    src = (Path(__file__).resolve().parents[1] / "src" / "case_api" / "db.py").read_text(
        encoding="utf-8"
    )
    assert "if production_lock_enabled() or not _can_use_local_fallback(exc):" in src
