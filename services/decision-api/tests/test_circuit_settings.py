"""ANUMANA_SIGNALS_* and ASYNC_OSINT_REDIS_* live on Settings, not raw env reads."""

from __future__ import annotations

_KEYS = (
    "ANUMANA_SIGNALS_TIMEOUT_SECONDS",
    "ANUMANA_SIGNALS_MAX_ATTEMPTS",
    "ANUMANA_SIGNALS_CIRCUIT_FAILURE_THRESHOLD",
    "ANUMANA_SIGNALS_CIRCUIT_RECOVERY_SECONDS",
    "ASYNC_OSINT_REDIS_TIMEOUT_SECONDS",
    "ASYNC_OSINT_REDIS_MAX_ATTEMPTS",
    "ASYNC_OSINT_REDIS_CIRCUIT_FAILURE_THRESHOLD",
    "ASYNC_OSINT_REDIS_CIRCUIT_RECOVERY_SECONDS",
)

# Env-less defaults: main.py / pipeline last-resort (0.08), not the drifted 0.05 table copy.
_DEFAULTS = {
    "anumana_signals_timeout_seconds": 0.08,
    "anumana_signals_max_attempts": 1,
    "anumana_signals_circuit_failure_threshold": 5,
    "anumana_signals_circuit_recovery_seconds": 2.0,
    "async_osint_redis_timeout_seconds": 0.08,
    "async_osint_redis_max_attempts": 1,
    "async_osint_redis_circuit_failure_threshold": 5,
    "async_osint_redis_circuit_recovery_seconds": 2.0,
}


def _clear_keys(monkeypatch) -> None:
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_exposes_anumana_and_async_osint_circuit_defaults(monkeypatch) -> None:
    from decision_api.config import Settings

    _clear_keys(monkeypatch)
    settings = Settings()
    for name, expected in _DEFAULTS.items():
        assert getattr(settings, name) == expected


def test_settings_reads_env_overrides(monkeypatch) -> None:
    from decision_api.config import Settings

    monkeypatch.setenv("ANUMANA_SIGNALS_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("ANUMANA_SIGNALS_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("ANUMANA_SIGNALS_CIRCUIT_FAILURE_THRESHOLD", "9")
    monkeypatch.setenv("ANUMANA_SIGNALS_CIRCUIT_RECOVERY_SECONDS", "4.5")
    monkeypatch.setenv("ASYNC_OSINT_REDIS_TIMEOUT_SECONDS", "0.15")
    monkeypatch.setenv("ASYNC_OSINT_REDIS_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("ASYNC_OSINT_REDIS_CIRCUIT_FAILURE_THRESHOLD", "7")
    monkeypatch.setenv("ASYNC_OSINT_REDIS_CIRCUIT_RECOVERY_SECONDS", "3.5")
    settings = Settings()
    assert settings.anumana_signals_timeout_seconds == 0.2
    assert settings.anumana_signals_max_attempts == 3
    assert settings.anumana_signals_circuit_failure_threshold == 9
    assert settings.anumana_signals_circuit_recovery_seconds == 4.5
    assert settings.async_osint_redis_timeout_seconds == 0.15
    assert settings.async_osint_redis_max_attempts == 2
    assert settings.async_osint_redis_circuit_failure_threshold == 7
    assert settings.async_osint_redis_circuit_recovery_seconds == 3.5


def test_policy_table_reads_settings_not_environ(monkeypatch) -> None:
    from decision_api import config

    monkeypatch.setattr(config.settings, "anumana_signals_timeout_seconds", 0.11)
    monkeypatch.setattr(config.settings, "anumana_signals_max_attempts", 4)
    monkeypatch.setattr(config.settings, "anumana_signals_circuit_failure_threshold", 8)
    monkeypatch.setattr(
        config.settings, "anumana_signals_circuit_recovery_seconds", 6.0
    )
    monkeypatch.setattr(config.settings, "async_osint_redis_timeout_seconds", 0.13)
    monkeypatch.setattr(config.settings, "async_osint_redis_max_attempts", 2)
    monkeypatch.setattr(
        config.settings, "async_osint_redis_circuit_failure_threshold", 6
    )
    monkeypatch.setattr(
        config.settings, "async_osint_redis_circuit_recovery_seconds", 7.0
    )
    # If the table still did os.environ.get, these would not appear.
    monkeypatch.delenv("ANUMANA_SIGNALS_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("ASYNC_OSINT_REDIS_TIMEOUT_SECONDS", raising=False)

    table = config.dependency_resilience_policy_table()
    assert table["anumana_signals"] == {
        "timeout_seconds": 0.11,
        "max_attempts": 4,
        "circuit_failure_threshold": 8,
        "circuit_recovery_seconds": 6.0,
        "on_failure": "SKIP",
    }
    assert table["async_osint_redis"] == {
        "timeout_seconds": 0.13,
        "max_attempts": 2,
        "circuit_failure_threshold": 6,
        "circuit_recovery_seconds": 7.0,
        "on_failure": "SKIP",
    }


def test_main_circuit_init_reads_settings() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1] / "src" / "decision_api" / "main.py"
    ).read_text(encoding="utf-8")
    for key in _KEYS:
        assert key not in text
    assert "settings.anumana_signals_timeout_seconds" in text
    assert "settings.async_osint_redis_timeout_seconds" in text
    assert "settings.anumana_signals_circuit_failure_threshold" in text
    assert "settings.async_osint_redis_circuit_failure_threshold" in text
