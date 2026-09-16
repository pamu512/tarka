#!/usr/bin/env python3
"""Guard: the REST facade gateway is gone from every deployment surface.

The gateway had zero consumers (frontend is REST-only; no SDK/docs examples;
lite stack skips it; CI exercised it only against itself) and duplicated the
REST planes it proxied. Per the one-job-one-service rule it was pruned. This
pins its absence from every surface that could resurrect it silently:
service directory, compose flavors, Helm templates/values/presets, CI jobs,
and the ops tooling that listed it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]

_SURFACES = [
    "services/graphql-gateway",
    "infra/deploy/docker-compose.yml",
    "infra/deploy/docker-compose.graph-env.yml",
    "infra/deploy/docker-compose.lite.yml",
    "infra/deploy/helm/fraud-stack/templates/graphql-gateway.yaml",
    "infra/deploy/helm/fraud-stack/values.yaml",
    "infra/deploy/helm/fraud-stack/templates/networkpolicy.yaml",
    "infra/deploy/helm/fraud-stack/templates/workload-operations.yaml",
    ".github/workflows/ci.yml",
    "tools/tarka.py",
]

_PRESETS = sorted((_REPO / "infra/deploy/helm/fraud-stack/presets").glob("*.yaml"))


class TestGatewayPruned(unittest.TestCase):
    def test_service_directory_absent(self) -> None:
        self.assertFalse(
            (_REPO / "services/graphql-gateway").exists(),
            "services/graphql-gateway still exists",
        )

    def test_no_deploy_surface_mentions_it(self) -> None:
        offenders: list[str] = []
        for rel in _SURFACES:
            p = _REPO / rel
            if p.exists() and "graphql-gateway" in p.read_text():
                offenders.append(rel)
        for p in _PRESETS:
            if "graphqlGateway" in p.read_text():
                offenders.append(str(p.relative_to(_REPO)))
        self.assertEqual(offenders, [], f"gateway references survive in: {offenders}")

    def test_values_block_gone(self) -> None:
        v = (_REPO / "infra/deploy/helm/fraud-stack/values.yaml").read_text()
        self.assertNotIn("graphqlGateway:", v)
        self.assertNotIn("graphqlHost", v)

    def test_needs_list_cleaned(self) -> None:
        ci = (_REPO / ".github/workflows/ci.yml").read_text()
        self.assertNotIn("test-graphql-gateway", ci)
        self.assertNotIn("graphql-gateway", ci)


if __name__ == "__main__":
    unittest.main()
