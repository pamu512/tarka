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
            path.write_text("SHADOW_LLM_BASE_URL=http://vllm:8000/v1\n", encoding="utf-8")
            self.assertEqual(
                setup_llm_env.prompt_llm(env_path=path, stdin_isatty=True),
                "already",
            )

    def test_wrote_env_is_owner_read_write_only(self) -> None:
        answers = iter(["http://vllm:8000/v1", "sekrit", "gpt-4"])
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
            self.assertIn("SHADOW_LLM_API_KEY=sekrit", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
