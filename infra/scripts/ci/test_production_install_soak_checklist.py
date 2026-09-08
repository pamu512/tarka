#!/usr/bin/env python3
"""G9 soak checklist + CLAIM_LOCK grade gate (not the grade itself)."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_CHECKLIST = _REPO / "docs" / "docs" / "guides" / "production-install-soak-checklist.md"
_CLAIM = _REPO / "docs" / "compliance" / "CLAIM_LOCK.md"
_SUPPORT = _REPO / "SUPPORT.md"
_DEPLOY = _REPO / "docs" / "docs" / "guides" / "deployment.md"
_INSTALL = _REPO / "docs" / "contracts" / "production-install-v1.md"


class TestProductionInstallSoakChecklist(unittest.TestCase):
    def test_checklist_is_pass_fail_named_pilot_gate(self) -> None:
        self.assertTrue(_CHECKLIST.is_file(), f"missing {_CHECKLIST.relative_to(_REPO)}")
        text = _CHECKLIST.read_text(encoding="utf-8")
        lowered = text.lower()
        for needle in (
            "named",
            "pass / fail",
            "digests pinned",
            "secrets rotated once",
            "oidc or api-key",
            "backup drill dated",
            "upgrade dry-run dated",
            "networkpolicy on",
            "buyer tps",
            "2 weeks observe",
            "handoff",
            "elv2",
            "g0–g8",
            "primary decisioner",
            "production-install-v1",
            "support.md",
            "deployment.md",
        ):
            self.assertIn(needle, lowered)
        self.assertIn("internal or buyer", lowered)
        self.assertNotIn("zero-downtime multi-region", lowered)
        self.assertNotRegex(text, r"\b(Sift|Forter|Riskified|Feedzai|Featurespace)\b")
        self.assertNotIn("GitLab-grade already achieved", text)
        self.assertIn("not the grade", lowered.replace("*", ""))

    def test_claim_lock_gates_grade_on_checklist_and_g0_g8(self) -> None:
        lock = _CLAIM.read_text(encoding="utf-8")
        self.assertIn("production-install-soak-checklist.md", lock)
        self.assertIn("G0–G8", lock)
        self.assertIn("named", lock.lower())
        self.assertIn("primary decisioner", lock.lower())
        self.assertIn("GitLab-grade install", lock)
        self.assertIn("production-install-v1.md", lock)

    def test_support_and_deployment_link_checklist(self) -> None:
        support = _SUPPORT.read_text(encoding="utf-8")
        deploy = _DEPLOY.read_text(encoding="utf-8")
        self.assertIn("production-install-soak-checklist.md", support)
        self.assertIn("production-install-v1.md", support)
        self.assertIn("production-install-soak-checklist.md", deploy)
        self.assertIn("SUPPORT.md", deploy)
        self.assertTrue(_DEPLOY.is_file())
        self.assertTrue(_INSTALL.is_file(), "G0 contract must be on tip")
        install = _INSTALL.read_text(encoding="utf-8")
        self.assertIn("GitLab-grade", install)
        self.assertIn("production-install-soak-checklist.md", install)
        for rel in (
            "docs/docs/guides/production-backup-restore.md",
            "docs/docs/guides/production-upgrade.md",
            "docs/docs/guides/production-secrets-rotation.md",
        ):
            self.assertTrue((_REPO / rel).is_file(), rel)
        checklist = _CHECKLIST.read_text(encoding="utf-8").lower()
        self.assertNotIn("not on master", checklist)
        self.assertNotIn("in-flight", checklist)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
