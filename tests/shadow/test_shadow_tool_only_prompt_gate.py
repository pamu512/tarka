"""Gate (Prompt 130): Shadow analyst system prompt forbids fabrication and mandates UNKNOWN + IP tool use."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
# ``backend`` is a package under ``tools/shadow/``; that directory must be on ``sys.path``.
_SHADOW_ROOT = _REPO / "tools" / "shadow"
if str(_SHADOW_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHADOW_ROOT))


def test_analyst_system_prompt_requires_unknown_and_ip_tool_not_guessing() -> None:
    """Asking for a random IP's owner must be answered via tools, not invented OSINT (prompt contract)."""
    from backend.agent.coordinator import build_analyst_system_prompt
    from backend.agent.personas import get_persona

    p = get_persona("general")
    text = build_analyst_system_prompt(p)
    lower = text.lower()
    assert "never fabricate" in lower
    assert "unknown" in lower
    assert "search_historical_overlap_tool" in text
    assert "warehouse_search_text_tool" in text or "warehouse_query_tool" in text
    assert "who owns this ip" in lower or "ip ownership" in lower


def test_supervisor_routing_includes_ip_owner_semantic_hint() -> None:
    """Supervisor analyst prototypes include IP-ownership phrasing (routes “who owns this IP?” to analyst)."""
    routing_py = _REPO / "tools" / "shadow" / "backend" / "agent" / "supervisor_routing.py"
    body = routing_py.read_text(encoding="utf-8").lower()
    assert "who owns this ip" in body
