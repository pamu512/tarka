#!/usr/bin/env python3
"""Guard: case-api SAR SFTP transport env must pass through core-api in lite.

The SAR state machine, SKIP LOCKED worker, and paramiko upload all exist, but
no deployment surface ever passed ``FINCEN_BSA_SFTP_*`` — the feature was
wired in code and dead in every real deployment (worker idles, queued intents
fail with SAR_SFTP_HOST_MISSING). This pins the passthrough in the lite
compose core-api block (case-api runs as a sub-app inside core-api's process,
so its worker reads core-api's environment).
"""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_COMPOSE = _REPO / "infra/deploy/docker-compose.lite.yml"


class TestSarTransportEnvPassthrough(unittest.TestCase):
    def test_core_api_block_passes_fincen_env(self) -> None:
        import re

        text = _COMPOSE.read_text()
        # Slice the core-api service block: from its key to the next top-level service key.
        m = re.search(r"^  core-api:\n.*?(?=^  [a-zA-Z][\w-]*:|\Z)", text, re.M | re.S)
        self.assertIsNotNone(m, "core-api service block not found")
        block = m.group(0)
        for var in (
            "FINCEN_BSA_SFTP_HOST",
            "FINCEN_BSA_SFTP_USER",
            "FINCEN_BSA_SFTP_PASSWORD",
            "FINCEN_BSA_SFTP_PORT",
            "FINCEN_BSA_SFTP_REMOTE_DIR",
        ):
            self.assertIn(f"{var}:", block, f"core-api block missing {var} passthrough")
            self.assertIn("${" + var, block, f"{var} must be interpolated from .env")


if __name__ == "__main__":
    unittest.main()
