"""
Back-compat module path for ``python -m shadow_agent.workers.nats_shadow_investigate``.

The durable JetStream pull consumer lives in
:mod:`orchestrator.workers.nats_shadow_investigate`.
"""

from __future__ import annotations

from shadow_agent.workers.shadow_investigate_handler import handle_shadow_investigate_payload

__all__ = ["handle_shadow_investigate_payload", "main", "run"]

try:
    from orchestrator.workers.nats_shadow_investigate import main, run
except ImportError:  # pragma: no cover — monorepo dev layout only

    def run() -> None:
        raise RuntimeError(
            "Install tarka-orchestrator on PYTHONPATH and run "
            "python -m orchestrator.workers.nats_shadow_investigate",
        )

    def main() -> None:
        run()
