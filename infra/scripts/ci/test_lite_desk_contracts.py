#!/usr/bin/env python3
"""Lite-desk buyer contracts (pyyaml); run: python3 infra/scripts/ci/test_lite_desk_contracts.py

Guards the clone-and-run pilot path against silent-failure regressions found in the
2026-09 buyer walkthrough: rules persistence, auto-case auth, data-plane auth parity,
host-port remaps, frontend API-key baking, and up_desk health breadth.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
LITE = ROOT / "infra/deploy/docker-compose.lite.yml"
FULL = ROOT / "infra/deploy/docker-compose.yml"
ENV_EXAMPLE = ROOT / "infra/deploy/env/community.env.example"
FRONTEND_DOCKERFILE = ROOT / "frontend/Dockerfile"
UP_DESK = ROOT / "scripts/oss/up_desk.sh"
RULES_MD = ROOT / "docs/docs/guides/rules.md"
CLONE_DEMO_MD = ROOT / "docs/docs/guides/clone-demo.md"
PILOT_PATH_MD = ROOT / "docs/docs/guides/pilot-path.md"
SRE_PROFILES_MD = ROOT / "docs/docs/operations/sre-compose-profiles.md"
INDEX_MD = ROOT / "docs/INDEX.md"


def _lite() -> dict:
    return yaml.safe_load(LITE.read_text(encoding="utf-8"))


def _core_env(doc: dict) -> dict:
    return doc["services"]["core-api"]["environment"]


class TestRulesPersistence(unittest.TestCase):
    def test_core_api_rules_dir_is_a_named_volume(self) -> None:
        doc = _lite()
        mounts = doc["services"]["core-api"]["volumes"]
        rules = [m for m in mounts if m.split(":")[-1].strip() == "/app/rules"]
        self.assertEqual(len(rules), 1, f"expected one /app/rules mount, got {mounts}")
        src = rules[0].split(":")[0].strip()
        self.assertIn(src, doc.get("volumes", {}), "rules mount source must be a named volume")
        self.assertFalse(src.startswith("."), "bind mount shadows baked-in pack files")

    def test_named_volume_declared(self) -> None:
        doc = _lite()
        self.assertIn("desk_rules", doc.get("volumes", {}))

    def test_full_compose_rules_dir_is_volume_too(self) -> None:
        doc = yaml.safe_load(FULL.read_text(encoding="utf-8"))
        mounts = doc["services"]["core-api"].get("volumes", [])
        rules = [m for m in mounts if m.split(":")[-1].strip() == "/app/rules"]
        self.assertEqual(len(rules), 1, f"expected one /app/rules mount, got {mounts}")
        src = rules[0].split(":")[0].strip()
        self.assertIn(src, doc.get("volumes", {}), "rules mount source must be a named volume")


class TestAutoCaseAuth(unittest.TestCase):
    """S1/B3: default lite stack must let decision-api's deny-review auto-case
    call authenticate against case-api (X-Internal-Token, same container)."""

    def test_core_api_case_internal_token_has_dev_default(self) -> None:
        env = _core_env(_lite())
        raw = str(env.get("CASE_INTERNAL_TOKEN", ""))
        self.assertIn("CASE_INTERNAL_TOKEN", raw, "token should stay overridable via env")
        default = raw.split(":-", 1)[1].rstrip("}").strip() if ":-" in raw else raw
        self.assertTrue(default, "CASE_INTERNAL_TOKEN interpolation default must be non-empty")

    def test_case_create_flag_gated_on_token(self) -> None:
        env = _core_env(_lite())
        flag = env.get("CASE_CREATE_ON_DENY_REVIEW", "")
        self.assertIn("CASE_INTERNAL_TOKEN", str(flag),
                      "auto-case flag must not enable case creation when token is empty")


class TestDataPlaneAuthParity(unittest.TestCase):
    """B5: data-plane and core-api must agree on insecure-mode defaults so a
    compose-direct buyer does not get 503s from /v1/events."""

    def test_data_plane_insecure_default_matches_core_api(self) -> None:
        doc = _lite()
        core = _core_env(doc).get("ALLOW_INSECURE_NO_AUTH")
        dp = doc["services"]["data-plane"]["environment"].get("ALLOW_INSECURE_NO_AUTH")
        self.assertEqual(core, dp,
                         f"data-plane insecure default {dp!r} diverges from core-api {core!r}")


class TestHostPortRemaps(unittest.TestCase):
    """B1: hardcoded host ports collide with a buyer's existing Postgres/Redis;
    published host sides must be env-overridable."""

    def test_postgres_host_port_interpolated(self) -> None:
        ports = _lite()["services"]["postgres"]["ports"]
        self.assertTrue(any("${TARKA_PG_PORT" in str(p) for p in ports), f"not remappable: {ports}")

    def test_redis_host_port_interpolated(self) -> None:
        ports = _lite()["services"]["redis"]["ports"]
        self.assertTrue(any("${TARKA_REDIS_PORT" in str(p) for p in ports), f"not remappable: {ports}")


class TestFrontendApiKeyBaking(unittest.TestCase):
    """B4: with API_KEYS set, the desk UI 401s unless the key was baked at build
    time; the Dockerfile must accept VITE_API_KEY and lite must pass it through."""

    def test_dockerfile_declares_arg(self) -> None:
        text = FRONTEND_DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("ARG VITE_API_KEY=", text, "frontend image must accept VITE_API_KEY build arg")
        self.assertIn("ENV VITE_API_KEY=", text, "arg must be exported into build env")

    def test_lite_passes_build_arg(self) -> None:
        doc = _lite()
        args = doc["services"]["frontend"]["build"].get("args", {})
        self.assertIn("VITE_API_KEY", args, "lite frontend build must pass VITE_API_KEY through")


class TestEnvExampleDocumentsLocalDeskControls(unittest.TestCase):
    """B1/B4/B5: the shipped env example must name the knobs a buyer actually
    needs: auth mode, port remaps, and the UI+REST both-work recipe."""

    def test_documents_allow_insecure_no_auth(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("ALLOW_INSECURE_NO_AUTH", text)

    def test_documents_port_remapping(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        for var in ("TARKA_PG_PORT", "TARKA_REDIS_PORT", "TARKA_CORE_PORT", "TARKA_FRONTEND_PORT"):
            self.assertIn(var, text, f"env example must mention {var}")

    def test_documents_ui_and_rest_recipe(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("VITE_API_KEY", text)
        self.assertIn("API_KEYS", text)


class TestUpDeskHealthBreadth(unittest.TestCase):
    """S2: the demo health gate waited on core-api alone; graph-service and
    frontend failures must surface, and probes must honor TARKA_*_PORT remaps."""

    def _script(self) -> str:
        return (ROOT / "scripts/oss/up_desk.sh").read_text(encoding="utf-8")

    def test_probes_graph_service_health(self) -> None:
        s = self._script()
        self.assertIn("/v1/health", s)
        self.assertIn("GRAPH_PORT", s)

    def test_probes_frontend(self) -> None:
        s = self._script()
        self.assertIn("FRONTEND_PORT", s)

    def test_probes_honor_env_file_port_remaps(self) -> None:
        s = self._script()
        self.assertIn("TARKA_CORE_PORT", s)
        self.assertIn("TARKA_GRAPH_PORT", s)
        self.assertIn("TARKA_FRONTEND_PORT", s)

    def test_unhealthy_plane_fails_loudly(self) -> None:
        s = self._script()
        self.assertRegex(s, r"\[fail\].*(graph|frontend)")


class TestDocsTruth(unittest.TestCase):
    """fix-8: the walkthrough's doc gaps stay fixed — docs name the auth the
    routes actually enforce and the planes the demo actually starts."""

    def test_rules_md_documents_local_desk_auth(self) -> None:
        s = RULES_MD.read_text(encoding="utf-8")
        self.assertIn("### Authentication (local desk vs production)", s)
        self.assertIn("X-Rule-Governance-Secret", s)
        self.assertIn("require_role_or_insecure_desk", s)

    def test_rules_md_auth_section_precedes_the_curl_journey(self) -> None:
        s = RULES_MD.read_text(encoding="utf-8")
        self.assertLess(
            s.index("### Authentication"),
            s.index("### Create a Rule Pack"),
        )

    def test_clone_demo_discloses_ingest_profile(self) -> None:
        s = CLONE_DEMO_MD.read_text(encoding="utf-8")
        self.assertIn("--profile ingest", s)
        self.assertIn("**not** started by `make demo`", s)

    def test_clone_demo_documents_port_remapping(self) -> None:
        s = CLONE_DEMO_MD.read_text(encoding="utf-8")
        self.assertIn("TARKA_PG_PORT", s)
        self.assertIn("TARKA_CORE_PORT", s)

    def test_pilot_path_doc_exists_and_is_linked(self) -> None:
        s = PILOT_PATH_MD.read_text(encoding="utf-8")
        self.assertIn("--profile ingest", s)
        self.assertIn("VITE_API_KEY", s)
        index = INDEX_MD.read_text(encoding="utf-8")
        self.assertIn("docs/guides/pilot-path.md", index)

    def test_sre_profiles_mentions_port_remapping(self) -> None:
        s = SRE_PROFILES_MD.read_text(encoding="utf-8")
        self.assertIn("TARKA_CORE_PORT", s)


if __name__ == "__main__":
    unittest.main()
