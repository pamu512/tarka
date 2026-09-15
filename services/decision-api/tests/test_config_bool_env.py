"""Empty-string env values for boolean settings must not crash Settings boot.

The lite compose emits ``CASE_CREATE_ON_DENY_REVIEW=''`` when no internal token
is set (nested interpolation ``${CASE_INTERNAL_TOKEN:+true}``). S1 semantics:
no token -> no auto-case, so empty parses to False instead of raising
pydantic ``bool_parsing`` (which permanently killed the container in CI).
"""

from __future__ import annotations


def test_empty_bool_env_is_false_not_crash(monkeypatch) -> None:
    from decision_api.config import Settings

    monkeypatch.setenv("CASE_CREATE_ON_DENY_REVIEW", "")
    settings = Settings()
    assert settings.case_create_on_deny_review is False


def test_explicit_bool_envs_still_parse(monkeypatch) -> None:
    from decision_api.config import Settings

    monkeypatch.setenv("CASE_CREATE_ON_DENY_REVIEW", "true")
    assert Settings().case_create_on_deny_review is True
    monkeypatch.setenv("CASE_CREATE_ON_DENY_REVIEW", "0")
    assert Settings().case_create_on_deny_review is False


def test_absent_env_keeps_default_true(monkeypatch) -> None:
    from decision_api.config import Settings

    monkeypatch.delenv("CASE_CREATE_ON_DENY_REVIEW", raising=False)
    assert Settings().case_create_on_deny_review is True
