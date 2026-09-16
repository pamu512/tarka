#!/usr/bin/env python3
"""Guard: every service Dockerfile that pip-installs must use the shared constraints file.

Unpinned ``pip install -e .`` resolves to whatever PyPI shipped overnight;
``infra/deploy/constraints.txt`` freezes resolution to the CI boot-verified set
(constraints file header documents the contract). Any Dockerfile with a
``pip install`` layer must COPY the constraints file and pass ``-c``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SERVICES = _REPO / "services"

# Toolchain / build-tool layers are exempt: they pin themselves (maturin>=1.7,<2.0,
# setuptools>=83.0.0, msgpack>=1.2.1) or manage the interpreter toolchain
# (pip/wheel upgrades). constraints.txt governs the shared web/runtime stack.
_TOOLCHAIN_RE = re.compile(
    r"pip install[^\n]*("
    r"pip|wheel|setuptools|maturin|msgpack"
    r")\b(?![\w.-])"
)


class TestDockerfileConstraints(unittest.TestCase):
    def _dockerfiles(self) -> list[Path]:
        return sorted(p for p in _SERVICES.glob("*/Dockerfile"))

    def test_fleet_finds_dockerfiles(self) -> None:
        self.assertGreater(len(self._dockerfiles()), 10)

    def test_every_pip_install_layer_is_constrained(self) -> None:
        offenders: list[str] = []
        for dockerfile in self._dockerfiles():
            text = dockerfile.read_text()
            has_copy = "constraints.txt" in text
            for m in re.finditer(r"^(?!\s*#)(\s*(RUN\s+)?|\s*&&\s*)(python\s+-m\s+)?pip install.*", text, re.M):
                layer = m.group(0)
                if _TOOLCHAIN_RE.search(layer):
                    continue
                if "-c /tmp/constraints.txt" not in layer:
                    offenders.append(f"{dockerfile.relative_to(_REPO)}: {layer.strip()[:90]}")
        self.assertEqual(
            offenders,
            [],
            "pip install layers without '-c /tmp/constraints.txt':\n" + "\n".join(offenders),
        )

    def test_constraints_copy_precedes_first_use(self) -> None:
        for dockerfile in self._dockerfiles():
            text = dockerfile.read_text()
            copy_at = text.find("COPY infra/deploy/constraints.txt")
            first_use = text.find("-c /tmp/constraints.txt")
            if first_use != -1:
                self.assertNotEqual(
                    copy_at,
                    -1,
                    f"{dockerfile.relative_to(_REPO)}: uses -c but never COPYs the file",
                )
                self.assertLess(
                    copy_at,
                    first_use,
                    f"{dockerfile.relative_to(_REPO)}: COPY of constraints must precede first use",
                )


if __name__ == "__main__":
    unittest.main()
