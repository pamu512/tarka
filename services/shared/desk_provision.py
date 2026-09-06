"""Named-desk defaults from desk_provision.json. Nonempty env wins."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_ID = "tarka.desk_provision/v1"
PATH_ENV = "TARKA_DESK_PROVISION_PATH"

_load_warned = False


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_raw(name: str) -> str | None:
    if name not in os.environ:
        return None
    return str(os.environ.get(name) or "")


def load_desk_provision(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read the provision file. Missing / invalid / wrong schema → {}."""
    global _load_warned
    raw_path = str(path) if path is not None else (_env_raw(PATH_ENV) or "").strip()
    if not raw_path:
        return {}
    p = Path(raw_path)
    if not p.is_file():
        if not _load_warned:
            log.warning("desk provision file missing: %s", p)
            _load_warned = True
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if not _load_warned:
            log.warning("desk provision file invalid: %s (%s)", p, exc)
            _load_warned = True
        return {}
    if not isinstance(data, dict) or str(data.get("schema_id") or "") != SCHEMA_ID:
        if not _load_warned:
            log.warning("desk provision schema_id ignored: %s", p)
            _load_warned = True
        return {}
    return data


def leftover_flag(env_name: str, provision_key: str) -> bool:
    raw = _env_raw(env_name)
    if raw is not None and raw.strip() != "":
        return _truthy(raw)
    leftover = load_desk_provision().get("leftover")
    if not isinstance(leftover, dict):
        return False
    return bool(leftover.get(provision_key))


def observe_auto_promote() -> bool | None:
    """Named-desk auto-promote gate. None = no desk_provision (file-only first-review)."""
    raw = _env_raw("TARKA_AUTO_PROMOTE")
    if raw is not None and raw.strip() != "":
        return _truthy(raw)
    data = load_desk_provision()
    if not data:
        return None
    observe = data.get("observe")
    if isinstance(observe, dict) and "auto_promote" in observe:
        return bool(observe.get("auto_promote"))
    return False


def host_auto_promote(file_flag: bool) -> bool:
    """First-review file AND named-desk gate. Named False blocks; None is file-only."""
    if observe_auto_promote() is False:
        return False
    return bool(file_flag)


def hunt_enabled() -> bool:
    raw = _env_raw("TARKA_HUNT_ENABLED")
    if raw is not None and raw.strip() != "":
        return _truthy(raw)
    hunt = load_desk_provision().get("hunt")
    if isinstance(hunt, dict) and "enabled" in hunt:
        return bool(hunt.get("enabled"))
    return True


def graph_service_url() -> str:
    if "GRAPH_SERVICE_URL" in os.environ:
        return str(os.environ.get("GRAPH_SERVICE_URL") or "").strip()
    graph = load_desk_provision().get("graph")
    if not isinstance(graph, dict):
        return ""
    return str(graph.get("service_url") or "").strip()


_HOOK_URL_ENV = {
    "enforcement": "TARKA_ENFORCEMENT_WEBHOOK_URL",
    "observe_notify": "TARKA_OBSERVE_NOTIFY_WEBHOOK_URL",
}
_HOOK_SECRET_ENV = {
    "enforcement": "TARKA_ENFORCEMENT_WEBHOOK_SECRET",
    "observe_notify": "TARKA_OBSERVE_NOTIFY_WEBHOOK_SECRET",
}


def hook_url(kind: str) -> str:
    env_name = _HOOK_URL_ENV.get(kind)
    if not env_name:
        return ""
    raw = _env_raw(env_name)
    if raw is not None:
        return raw.strip()
    hooks = load_desk_provision().get("hooks")
    if not isinstance(hooks, dict):
        return ""
    block = hooks.get(kind)
    if not isinstance(block, dict):
        return ""
    return str(block.get("url") or "").strip()


def hook_secret(kind: str) -> str:
    default_env = _HOOK_SECRET_ENV.get(kind)
    if not default_env:
        return ""
    raw = _env_raw(default_env)
    if raw is not None and raw.strip() != "":
        return raw.strip()
    hooks = load_desk_provision().get("hooks")
    secret_env = default_env
    if isinstance(hooks, dict):
        block = hooks.get(kind)
        if isinstance(block, dict) and str(block.get("secret_env") or "").strip():
            secret_env = str(block.get("secret_env")).strip()
    named = _env_raw(secret_env)
    return (named or "").strip()


def observe_notify_store() -> str:
    raw = _env_raw("TARKA_OBSERVE_NOTIFY_STORE")
    if raw is not None and raw.strip() != "":
        token = raw.strip().lower()
        if token in {"postgres", "file"}:
            return token
        return "file"
    profile = str(load_desk_provision().get("profile") or "").strip().lower()
    if profile == "product":
        return "postgres"
    return "file"


def shadow_agent_should_start(
    *,
    llm_url: str | None = None,
    desk_profile: str | None = None,
) -> bool:
    profile = (desk_profile or "").strip().lower()
    if profile == "demo":
        return False
    url = llm_url if llm_url is not None else (_env_raw("OPENAI_BASE_URL") or "")
    if not str(url).strip():
        return False
    shadow = load_desk_provision().get("shadow_agent")
    if isinstance(shadow, dict) and "start_when_llm_url" in shadow:
        return bool(shadow.get("start_when_llm_url"))
    return True
