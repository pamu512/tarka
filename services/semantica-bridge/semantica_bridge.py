"""Optional Semantica mirror for decision context (advise/demo only).

Never wired into evaluate allow/deny. Enable with SEMANTICA_BRIDGE_ENABLED=1.
If the `semantica` package is not installed, uses an in-process stub store so
offline smoke still works.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("semantica-bridge")

_LOCK = threading.RLock()
_STUB: dict[str, dict[str, Any]] = {}
_STUB_EDGES: list[tuple[str, str, str]] = []


def bridge_enabled() -> bool:
    raw = (os.environ.get("SEMANTICA_BRIDGE_ENABLED") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _pin_ok() -> bool:
    """Require SEMANTICA_PIN when real package is used."""
    return bool((os.environ.get("SEMANTICA_PIN") or "").strip())


@dataclass
class MirrorResult:
    semantica_decision_id: str | None
    backend: str
    ok: bool
    detail: str = ""


def mirror_decision(
    *,
    category: str,
    scenario: str,
    reasoning: str,
    outcome: str,
    confidence: float | None = None,
    parent_semantica_id: str | None = None,
    relationship: str = "INFLUENCED",
) -> MirrorResult:
    if not bridge_enabled():
        return MirrorResult(None, "off", False, "disabled")

    use_real = _try_real_semantica and _pin_ok()
    if use_real:
        try:
            return _mirror_real(
                category=category,
                scenario=scenario,
                reasoning=reasoning,
                outcome=outcome,
                confidence=confidence,
                parent_semantica_id=parent_semantica_id,
                relationship=relationship,
            )
        except Exception as e:
            log.warning("semantica_real_mirror_failed falling_back_stub err=%s", e)

    sid = f"sem_{uuid.uuid4().hex}"
    with _LOCK:
        _STUB[sid] = {
            "category": category,
            "scenario": scenario,
            "reasoning": reasoning,
            "outcome": outcome,
            "confidence": confidence,
        }
        if parent_semantica_id:
            _STUB_EDGES.append((parent_semantica_id, sid, relationship.upper()))
    return MirrorResult(sid, "stub", True)


def stub_chain(decision_id: str) -> dict[str, Any]:
    """Offline chain for stub backend (parents)."""
    nodes = []
    edges = []
    cur = decision_id
    seen = set()
    with _LOCK:
        while cur and cur not in seen:
            seen.add(cur)
            if cur in _STUB:
                nodes.append({"id": cur, **_STUB[cur]})
            parents = [a for a, b, r in _STUB_EDGES if b == cur]
            for p in parents:
                rel = next(r for a, b, r in _STUB_EDGES if a == p and b == cur)
                edges.append({"from": p, "to": cur, "relationship": rel})
            cur = parents[0] if parents else ""
    return {"nodes": nodes, "edges": edges}


_try_real_semantica = True


def _mirror_real(
    *,
    category: str,
    scenario: str,
    reasoning: str,
    outcome: str,
    confidence: float | None,
    parent_semantica_id: str | None,
    relationship: str,
) -> MirrorResult:
    if not _pin_ok():
        raise RuntimeError("SEMANTICA_PIN required when using real semantica package")
    from semantica.context import ContextGraph  # type: ignore

    # ponytail: process-global ContextGraph — ceiling is single-process demo;
    # upgrade path is Semantica HTTP service + durable store.
    global _CTX
    if _CTX is None:
        _CTX = ContextGraph(advanced_analytics=True)
    kwargs: dict[str, Any] = {
        "category": category,
        "scenario": scenario,
        "reasoning": reasoning,
        "outcome": outcome,
    }
    if confidence is not None:
        kwargs["confidence"] = confidence
    decision_id = _CTX.record_decision(**kwargs)
    if parent_semantica_id:
        _CTX.add_causal_relationship(
            parent_semantica_id, decision_id, relationship_type=relationship.upper()
        )
    return MirrorResult(str(decision_id), "semantica", True)


_CTX: Any = None


def reset_stub_for_tests() -> None:
    with _LOCK:
        _STUB.clear()
        _STUB_EDGES.clear()
