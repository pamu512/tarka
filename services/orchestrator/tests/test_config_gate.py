"""Gate: typed orchestrator settings replace raw env lookups in worker/messaging paths."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from config import (
    OrchestratorSettings,
    get_settings,
    reset_settings_cache,
)  # noqa: E402
from workers.outbox_processor import load_config  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings_cache()
    monkeypatch.delenv("OUTBOX_POLL_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("OUTBOX_BATCH_SIZE", raising=False)
    monkeypatch.delenv("RULE_SHADOW_TEST_HIGH_POSITIVE_RATE_THRESHOLD", raising=False)
    reset_settings_cache()


def test_outbox_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTBOX_POLL_INTERVAL_SECONDS", "3.5")
    monkeypatch.setenv("OUTBOX_BATCH_SIZE", "250")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    reset_settings_cache()

    settings = get_settings()
    assert settings.outbox_poll_interval_seconds == pytest.approx(3.5)
    assert settings.outbox_batch_size == 250
    assert settings.log_level == "DEBUG"


def test_jetstream_settings_defaults() -> None:
    settings = get_settings()
    assert settings.shadow_investigate_jetstream_fetch_batch == 10
    assert settings.consortium_labels_jetstream_fetch_batch == 10
    assert settings.tarka_events_jetstream_max_bytes > 0


def test_operational_signal_constraint_settings_defaults() -> None:
    settings = get_settings()
    assert settings.operational_signal_idempotency_ttl_sec == 3600
    assert settings.operational_signal_idempotency_key_max_length == 255
    assert settings.operational_signal_reason_code_max_length == 32


def test_rule_shadow_test_scorecard_threshold_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RULE_SHADOW_TEST_HIGH_POSITIVE_RATE_THRESHOLD", "0.95")
    monkeypatch.setenv("RULE_SHADOW_TEST_COHORT_LIMIT", "500")
    reset_settings_cache()

    settings = get_settings()
    assert settings.rule_shadow_test_high_positive_rate_threshold == pytest.approx(0.95)
    assert settings.rule_shadow_test_cohort_limit == 500


def test_load_config_uses_typed_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_AUDIT_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("OUTBOX_POLL_INTERVAL_SECONDS", "1.5")
    monkeypatch.setenv("OUTBOX_BATCH_SIZE", "42")
    reset_settings_cache()

    config = load_config()
    assert config.poll_interval_sec == pytest.approx(1.5)
    assert config.batch_size == 42


def test_configured_modules_avoid_os_environ() -> None:
    module_paths = [
        _SRC_ORCH / "orchestrator" / "config.py",
        _SRC_ORCH / "orchestrator" / "workers" / "outbox_processor.py",
        _SRC_ORCH / "orchestrator" / "messaging" / "nats_jetstream.py",
        _SRC_ORCH / "orchestrator" / "messaging" / "shadow_investigate_jetstream.py",
        _SRC_ORCH / "orchestrator" / "messaging" / "labels_jetstream.py",
        _SRC_ORCH / "orchestrator" / "queues" / "shadow_dispatch.py",
        _SRC_ORCH / "orchestrator" / "services" / "operational_signal_ingress.py",
        _SRC_ORCH / "orchestrator" / "rule_shadow_test.py",
        _SRC_ORCH / "orchestrator" / "workers" / "nats_shadow_investigate.py",
    ]
    for path in module_paths:
        if path.name == "config.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(getattr(node.func, "attr", None), str)
            and node.func.attr in {"get", "getenv"}
            and isinstance(getattr(node.func, "value", None), ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "os"
            and node.func.value.attr == "environ"
        ]
        assert not offenders, f"{path.name} still uses os.environ lookups"


def test_orchestrator_settings_rejects_invalid_log_level() -> None:
    with pytest.raises(ValidationError):
        OrchestratorSettings(log_level="VERBOSE")
