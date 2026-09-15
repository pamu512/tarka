#!/usr/bin/env python3
"""Guard: integration-ingress container must honor the startup-migration gate.

Its CMD hard-runs ``alembic upgrade head`` on every boot — DDL against whatever
DATABASE_URL points at. Compose sets ``TARKA_SKIP_STARTUP_MIGRATIONS=1`` for it
(same contract as case-api), but the CMD never read the variable: unconditional
DDL on every restart. This pins that the boot script gates migrations on the
same env var, keeping ``alembic`` for first-boot/ops contexts where the gate is
unset.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_DOCKERFILE = _REPO / "services/integration-ingress/Dockerfile"


class TestIngressMigrationGate(unittest.TestCase):
    def test_cmd_gates_alembic_on_skip_env(self) -> None:
        text = _DOCKERFILE.read_text()
        self.assertIn("TARKA_SKIP_STARTUP_MIGRATIONS", text)
        # The alembic invocation must be conditional, not unconditional.
        cmd = next(
            line for line in text.splitlines() if line.startswith("CMD ")
        )
        self.assertNotIn('"alembic upgrade head && exec', cmd)
        self.assertIn("alembic upgrade head", cmd, "first-boot migration path kept")

    def test_compose_sets_the_gate(self) -> None:
        compose = (_REPO / "infra/deploy/docker-compose.yml").read_text()
        self.assertIn("TARKA_SKIP_STARTUP_MIGRATIONS", compose)


if __name__ == "__main__":
    unittest.main()
