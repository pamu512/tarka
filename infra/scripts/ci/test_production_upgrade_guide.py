#!/usr/bin/env python3
"""G7 production-upgrade guide is present and scoped (not multi-region / G8 SUPPORT)."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_GUIDE = _REPO / "docs" / "docs" / "guides" / "production-upgrade.md"
_BACKUP = _REPO / "docs" / "docs" / "guides" / "production-backup-restore.md"
_INSTALL = _REPO / "docs" / "contracts" / "production-install-v1.md"


class TestProductionUpgradeGuide(unittest.TestCase):
    def test_guide_covers_upgrade_rollback_and_kill_switches(self) -> None:
        self.assertTrue(_GUIDE.is_file(), f"missing {_GUIDE.relative_to(_REPO)}")
        text = _GUIDE.read_text(encoding="utf-8")
        lowered = text.lower()
        for needle in (
            "preflight",
            "helm upgrade",
            "/v1/decisions/evaluate",
            "helm rollback",
            "expand/contract",
            "never silent destroy",
            "emit_only",
            "mode: disabled",
            "sha256:",
            "production-install-v1",
            "deployment.md",
        ):
            self.assertIn(needle, lowered if needle.islower() else text)
        self.assertIn("TARKA_ENFORCEMENT_MODE", text)
        self.assertIn("G6", text)
        self.assertIn("production-backup-restore.md", text)
        self.assertIn("G8", text)
        self.assertNotIn("zero-downtime multi-region", lowered)
        # Locks
        self.assertIn("ELv2", text)
        self.assertNotRegex(text, r"\b(Sift|Forter|Riskified|Feedzai|Featurespace)\b")

    def test_g6_backup_link_does_not_block(self) -> None:
        text = _GUIDE.read_text(encoding="utf-8")
        self.assertIn("production-backup-restore.md", text)
        if _BACKUP.is_file():
            self.assertIn("production-backup-restore.md", text)
        # Missing G6 file is allowed — playbook must not require it to exist.
        self.assertTrue(_GUIDE.is_file())

    def test_links_production_install_and_deployment(self) -> None:
        text = _GUIDE.read_text(encoding="utf-8")
        self.assertIn("production-install-v1.md", text)
        self.assertIn("deployment.md", text)
        self.assertTrue(
            (_REPO / "docs" / "docs" / "guides" / "deployment.md").is_file()
        )
        # G0 contract may still be in-flight on another branch.
        if _INSTALL.is_file():
            self.assertIn("GitLab-grade", _INSTALL.read_text(encoding="utf-8"))

    def test_pack_loader_fail_closed_unknown_version(self) -> None:
        loader = (
            _REPO / "services" / "decision-api" / "src" / "decision_api" / "json_rules.py"
        )
        text = loader.read_text(encoding="utf-8")
        self.assertIn("unsupported pack version", text)
        self.assertIn("fail-closed, not loaded", text)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
