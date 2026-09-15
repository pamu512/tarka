#!/usr/bin/env python3
"""Compose guard (D5-4): the shadow.investigate worker is actually deployed.

The orchestrator publishes ``shadow.investigate`` on REVIEW and two full consumer
implementations exist (orchestrator/workers/nats_shadow_investigate.py +
shadow_agent/workers/) — but no compose flavor ever ran them, so shadow
investigations were dropped on the floor in every deployment. This guard pins:

1. docker-compose.yml defines ``shadow-investigate-worker`` (JetStream pull
   consumer, outbox-processor style) in the NATS-bearing profiles;
2. the orchestrator image ships ``shadow_agent`` (the worker's runtime import)
   and ``nats-py`` (the ``worker`` extra) — neither was in the image before.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_COMPOSE = _REPO / "infra" / "deploy" / "docker-compose.yml"
_DOCKERFILE = _REPO / "services" / "orchestrator" / "Dockerfile"


def _service_block(text: str, name: str) -> str:
    """Return the YAML block for a top-level compose service, indented-code style."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == f"  {name}:":
            start = i
            break
    if start is None:
        raise AssertionError(f"service {name!r} not found in compose file")
    block = [lines[start]]
    for follow in lines[start + 1 :]:
        if follow and not follow.startswith(" "):
            break
        block.append(follow)
    return "\n".join(block)


class TestShadowInvestigateWorkerDeployed(unittest.TestCase):
    def test_compose_defines_worker_service(self) -> None:
        text = _COMPOSE.read_text()
        block = _service_block(text, "shadow-investigate-worker")
        self.assertIn('-m", "workers.nats_shadow_investigate', block)
        self.assertIn("profiles: [streaming, analytics, full]", block)
        self.assertIn("NATS_URL: nats://nats:4222", block)
        self.assertIn("SHADOW_DATABASE_URL:", block)

    def test_worker_waits_for_orchestrator(self) -> None:
        block = _service_block(_COMPOSE.read_text(), "shadow-investigate-worker")
        self.assertIn("depends_on:", block)
        self.assertRegex(block, r"depends_on:\s*\n\s+- (orchestrator|nats)")

    def test_image_ships_tarka_evidence_protobuf(self) -> None:
        """Worker chain imports tarka.evidence wire (pure-python); image must carry it."""
        dockerfile = _DOCKERFILE.read_text()
        self.assertIn("crates/tarka-py/python/tarka", dockerfile)

    def test_tarka_package_imports_without_compiled_ext(self) -> None:
        """The policy wheel must import in protobuf-only contexts (worker images)."""
        init = (_REPO / "crates/tarka-py/python/tarka/__init__.py").read_text()
        self.assertIn("except ImportError", init)

    def test_orchestrator_image_ships_services_shared(self) -> None:
        """deps/v1_api_guard imports minute_rate_limit from services/shared;
        without it the uvicorn API entrypoint dies at import (workers fine)."""
        dockerfile = _DOCKERFILE.read_text()
        self.assertIn("COPY services/shared /app/services/shared", dockerfile)


class TestConstraintsAdoption(unittest.TestCase):
    """Fresh builds must resolve inside the verified-good cap set."""

    SERVICES = (
        "core-api",
        "orchestrator",
        "graph-service",
        "data-plane",
        "integration-ingress",
        "case-api",
        "event-ingest",
    )

    def test_constraints_file_covers_verified_set(self) -> None:
        text = (_REPO / "infra/deploy/constraints.txt").read_text()
        for cap in ("fastapi<", "pydantic<", "uvicorn<", "starlette<", "sqlalchemy<"):
            self.assertIn(cap, text)

    def test_every_service_dockerfile_uses_constraints(self) -> None:
        missing = []
        for svc in self.SERVICES:
            dockerfile = (_REPO / f"services/{svc}/Dockerfile").read_text()
            if "-c /tmp/constraints.txt" not in dockerfile:
                missing.append(svc)
        self.assertEqual(missing, [])

    def test_orchestrator_image_ships_shadow_agent(self) -> None:
        dockerfile = _DOCKERFILE.read_text()
        self.assertIn(
            "COPY services/shadow_agent /app/services/shadow_agent",
            dockerfile,
            "orchestrator image must ship shadow_agent for the worker import",
        )
        self.assertIn(
            "/app/services/shadow_agent",
            dockerfile.split("ENV PYTHONPATH=", 1)[1].split("\n", 1)[0],
            "image PYTHONPATH must include /app/services/shadow_agent "
            "(shadow_agent's internal imports are flat: from ai_gateway…)",
        )

    def test_orchestrator_image_installs_nats_py(self) -> None:
        dockerfile = _DOCKERFILE.read_text()
        self.assertIn(
            "nats-py",
            dockerfile,
            "orchestrator image must install the worker extra (nats-py)",
        )


if __name__ == "__main__":
    unittest.main()
