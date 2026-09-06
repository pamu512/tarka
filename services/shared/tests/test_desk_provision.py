from __future__ import annotations

import json

import pytest

from desk_provision import (
    SCHEMA_ID,
    graph_service_url,
    hook_secret,
    hook_url,
    hunt_enabled,
    leftover_flag,
    load_desk_provision,
    observe_notify_store,
    shadow_agent_should_start,
)


def _write(tmp_path, payload: dict, name: str = "desk_provision.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_missing_path_is_empty(monkeypatch):
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    assert load_desk_provision() == {}


def test_missing_file_is_empty(tmp_path, monkeypatch):
    missing = tmp_path / "nope.json"
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(missing))
    assert load_desk_provision() == {}


def test_bad_schema_id_ignored(tmp_path, monkeypatch):
    path = _write(tmp_path, {"schema_id": "other", "leftover": {"multi_analyst_claim": True}})
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    assert load_desk_provision() == {}
    assert leftover_flag("TARKA_MULTI_ANALYST_CLAIM", "multi_analyst_claim") is False


def test_load_valid_file(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        {
            "schema_id": SCHEMA_ID,
            "profile": "product",
            "hunt": {"enabled": False},
            "graph": {"service_url": "http://graph-service:8001"},
            "leftover": {
                "flag_mints_leftover": True,
                "multi_analyst_claim": True,
                "qa_queue_isolates": True,
                "receipt_brief_enabled": True,
            },
            "shadow_agent": {"start_when_llm_url": True},
        },
    )
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.delenv("TARKA_MULTI_ANALYST_CLAIM", raising=False)
    monkeypatch.delenv("TARKA_FLAG_MINTS_LEFTOVER", raising=False)
    monkeypatch.delenv("TARKA_QA_QUEUE_ISOLATES", raising=False)
    monkeypatch.delenv("TARKA_RECEIPT_BRIEF", raising=False)
    monkeypatch.delenv("TARKA_HUNT_ENABLED", raising=False)
    monkeypatch.delenv("GRAPH_SERVICE_URL", raising=False)
    loaded = load_desk_provision()
    assert loaded["schema_id"] == SCHEMA_ID
    assert leftover_flag("TARKA_FLAG_MINTS_LEFTOVER", "flag_mints_leftover") is True
    assert leftover_flag("TARKA_MULTI_ANALYST_CLAIM", "multi_analyst_claim") is True
    assert leftover_flag("TARKA_QA_QUEUE_ISOLATES", "qa_queue_isolates") is True
    assert leftover_flag("TARKA_RECEIPT_BRIEF", "receipt_brief_enabled") is True
    assert hunt_enabled() is False
    assert graph_service_url() == "http://graph-service:8001"


def test_env_wins_over_file(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        {
            "schema_id": SCHEMA_ID,
            "leftover": {"multi_analyst_claim": True, "flag_mints_leftover": True},
            "hunt": {"enabled": False},
            "graph": {"service_url": "http://from-file:8001"},
        },
    )
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.setenv("TARKA_MULTI_ANALYST_CLAIM", "0")
    monkeypatch.setenv("TARKA_FLAG_MINTS_LEFTOVER", "false")
    monkeypatch.setenv("TARKA_HUNT_ENABLED", "1")
    monkeypatch.setenv("GRAPH_SERVICE_URL", "")
    assert leftover_flag("TARKA_MULTI_ANALYST_CLAIM", "multi_analyst_claim") is False
    assert leftover_flag("TARKA_FLAG_MINTS_LEFTOVER", "flag_mints_leftover") is False
    assert hunt_enabled() is True
    assert graph_service_url() == ""


def test_leftover_defaults_false_without_file(monkeypatch):
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    monkeypatch.delenv("TARKA_FLAG_MINTS_LEFTOVER", raising=False)
    monkeypatch.delenv("TARKA_MULTI_ANALYST_CLAIM", raising=False)
    monkeypatch.delenv("TARKA_QA_QUEUE_ISOLATES", raising=False)
    monkeypatch.delenv("TARKA_RECEIPT_BRIEF", raising=False)
    assert leftover_flag("TARKA_FLAG_MINTS_LEFTOVER", "flag_mints_leftover") is False
    assert leftover_flag("TARKA_MULTI_ANALYST_CLAIM", "multi_analyst_claim") is False
    assert leftover_flag("TARKA_QA_QUEUE_ISOLATES", "qa_queue_isolates") is False
    assert leftover_flag("TARKA_RECEIPT_BRIEF", "receipt_brief_enabled") is False


def test_hunt_defaults_true(monkeypatch):
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    monkeypatch.delenv("TARKA_HUNT_ENABLED", raising=False)
    assert hunt_enabled() is True


def test_shadow_agent_demo_never(monkeypatch):
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    assert shadow_agent_should_start(llm_url="http://llm", desk_profile="demo") is False


def test_shadow_agent_product_needs_llm_url(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        {"schema_id": SCHEMA_ID, "shadow_agent": {"start_when_llm_url": True}},
    )
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert shadow_agent_should_start(desk_profile="product") is False
    assert shadow_agent_should_start(llm_url="http://llm", desk_profile="product") is True


def test_invalid_json_ignored(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    assert load_desk_provision() == {}


def test_hook_url_env_wins(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        {
            "schema_id": SCHEMA_ID,
            "hooks": {
                "enforcement": {
                    "url": "http://from-file/enf",
                    "secret_env": "FILE_ENF_SECRET",
                },
                "observe_notify": {
                    "url": "http://from-file/obs",
                    "secret_env": "FILE_OBS_SECRET",
                },
            },
        },
    )
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_URL", "http://from-env/enf")
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_URL", "http://from-env/obs")
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_SECRET", "env-enf")
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_SECRET", "env-obs")
    assert hook_url("enforcement") == "http://from-env/enf"
    assert hook_url("observe_notify") == "http://from-env/obs"
    assert hook_secret("enforcement") == "env-enf"
    assert hook_secret("observe_notify") == "env-obs"


def test_hook_url_from_file_and_named_secret(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        {
            "schema_id": SCHEMA_ID,
            "hooks": {
                "enforcement": {
                    "url": "http://from-file/enf",
                    "secret_env": "FILE_ENF_SECRET",
                }
            },
        },
    )
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.delenv("TARKA_ENFORCEMENT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TARKA_ENFORCEMENT_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("FILE_ENF_SECRET", "named-secret")
    assert hook_url("enforcement") == "http://from-file/enf"
    assert hook_secret("enforcement") == "named-secret"


def test_empty_hook_url_is_off(monkeypatch):
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    monkeypatch.delenv("TARKA_ENFORCEMENT_WEBHOOK_URL", raising=False)
    assert hook_url("enforcement") == ""
    assert hook_secret("enforcement") == ""


def test_observe_notify_store_env_wins(tmp_path, monkeypatch):
    path = _write(tmp_path, {"schema_id": SCHEMA_ID, "profile": "product"})
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_STORE", "file")
    assert observe_notify_store() == "file"
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_STORE", "postgres")
    assert observe_notify_store() == "postgres"


def test_observe_notify_store_product_profile(tmp_path, monkeypatch):
    path = _write(tmp_path, {"schema_id": SCHEMA_ID, "profile": "product"})
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(path))
    monkeypatch.delenv("TARKA_OBSERVE_NOTIFY_STORE", raising=False)
    assert observe_notify_store() == "postgres"
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    assert observe_notify_store() == "file"
