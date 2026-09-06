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
