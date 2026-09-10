#!/usr/bin/env python3
"""Offline tests for scripts/oss/setup_llm_env.py (stdlib)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_OSS = _REPO / "scripts" / "oss"
if str(_OSS) not in sys.path:
    sys.path.insert(0, str(_OSS))

import setup_llm_env  # noqa: E402


class TestSetupLlmEnv(unittest.TestCase):
    def test_empty_url_renders_nothing(self) -> None:
        self.assertEqual(setup_llm_env.render_llm_block(url="", api_key="x", model="m"), "")
        self.assertEqual(setup_llm_env.render_advise_block(url="", api_key="x", model="m"), "")

    def test_url_writes_vllm_compat_not_azure_backend_name(self) -> None:
        block = setup_llm_env.render_llm_block(
            url="https://example.openai.azure.com/v1",
            api_key="sekrit",
            model="gpt-4",
        )
        self.assertIn("SHADOW_LLM_BACKEND=vllm", block)
        self.assertIn("SHADOW_LLM_BASE_URL=https://example.openai.azure.com/v1", block)
        self.assertIn("SHADOW_LLM_API_KEY=sekrit", block)
        self.assertNotIn("azure\n", block)
        self.assertNotIn("VITE_", block)

    def test_advise_url_writes_openai_compat_not_frontend_key(self) -> None:
        block = setup_llm_env.render_advise_block(
            url="https://bedrock-gateway.example/v1",
            api_key="sekrit",
            model="gpt-4",
        )
        self.assertIn("OPENAI_BASE_URL=https://bedrock-gateway.example/v1", block)
        self.assertIn("OPENAI_API_KEY=sekrit", block)
        self.assertIn("OPENAI_MODEL=gpt-4", block)
        self.assertNotIn("VITE_", block)
        self.assertNotIn("VITE_OPENAI_API_KEY", block)
        self.assertNotIn("SHADOW_LLM_", block)

    def test_non_tty_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            self.assertEqual(
                setup_llm_env.prompt_llm(env_path=path, stdin_isatty=False),
                "skip",
            )
            self.assertFalse(path.exists())

    def test_already_set_skips_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "OPENAI_BASE_URL=http://vllm:8000/v1\nSHADOW_LLM_BASE_URL=http://vllm:8000/v1\n",
                encoding="utf-8",
            )
            self.assertEqual(
                setup_llm_env.prompt_llm(env_path=path, stdin_isatty=True),
                "already",
            )

    def test_empty_advise_url_skips_openai_write(self) -> None:
        answers = iter(["", "", "", ""])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            self.assertEqual(
                setup_llm_env.prompt_llm(
                    env_path=path,
                    stdin_isatty=True,
                    input_fn=lambda _p: next(answers),
                ),
                "skip",
            )
            self.assertFalse(path.exists())

    def test_wrote_advise_openai_env_is_owner_read_write_only(self) -> None:
        # Advise URL/key/model, then skip ingest sidecar.
        answers = iter(["http://vllm:8000/v1", "sekrit", "gpt-4", ""])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            self.assertEqual(
                setup_llm_env.prompt_llm(
                    env_path=path,
                    stdin_isatty=True,
                    input_fn=lambda _p: next(answers),
                ),
                "wrote",
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            text = path.read_text(encoding="utf-8")
            self.assertIn("OPENAI_API_KEY=sekrit", text)
            self.assertIn("OPENAI_BASE_URL=http://vllm:8000/v1", text)
            self.assertNotIn("VITE_", text)
            self.assertNotIn("SHADOW_LLM_API_KEY", text)

    def test_wrote_ingest_shadow_llm_separate_from_advise(self) -> None:
        # Skip Advise, write ingest sidecar SHADOW_LLM_*.
        answers = iter(["", "http://vllm:8000/v1", "ingest-sekrit", "llama"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            self.assertEqual(
                setup_llm_env.prompt_llm(
                    env_path=path,
                    stdin_isatty=True,
                    input_fn=lambda _p: next(answers),
                ),
                "wrote",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("SHADOW_LLM_API_KEY=ingest-sekrit", text)
            self.assertNotIn("OPENAI_API_KEY", text)
            self.assertNotIn("VITE_", text)

    def test_frontend_env_never_takes_openai_key(self) -> None:
        dockerfile = _REPO / "frontend" / "Dockerfile"
        vite = _REPO / "frontend" / "src" / "vite-env.d.ts"
        body = dockerfile.read_text(encoding="utf-8") + "\n" + vite.read_text(encoding="utf-8")
        self.assertNotIn("OPENAI_API_KEY", body)
        self.assertNotIn("VITE_OPENAI", body)
        self.assertIn("VITE_INVESTIGATION_AGENT_URL", body)

    def test_day1_scripts_gate_ia_on_openai_url_not_shadow_llm(self) -> None:
        desk = (_REPO / "scripts" / "oss" / "up_desk.sh").read_text(encoding="utf-8")
        product = (_REPO / "scripts" / "oss" / "up_product.sh").read_text(encoding="utf-8")
        self.assertIn("OPENAI_BASE_URL", desk)
        self.assertIn("docker-compose.investigation.yml", desk)
        self.assertIn("OPENAI_BASE_URL", product)
        self.assertIn("docker-compose.investigation.yml", product)
        self.assertIn("SHADOW_LLM_BASE_URL", product)
        self.assertIn("--profile llm", product)
        self.assertNotIn("VITE_OPENAI_API_KEY", desk + product)


if __name__ == "__main__":
    unittest.main()
