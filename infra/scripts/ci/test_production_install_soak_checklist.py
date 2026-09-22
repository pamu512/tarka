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
_BINDER = _REPO / "docs" / "pilots" / "internal-lab" / "README.md"
_DRY_RUN = _REPO / "scripts" / "oss" / "soak_backup_upgrade_dry_run.py"
_VENDOR_RE = r"\b(Sift|Forter|Riskified|Feedzai|Featurespace)\b"


def _placeholder(value: str) -> bool:
    token = (value or "").strip().strip("`").strip()
    if not token:
        return True
    if set(token) <= {"_"}:
        return True
    # "prod-on-k8s / other: ________" stays unsigned on the fill-in side
    if "________" in token:
        return True
    return False


def _markdown_rows(text: str, header_needle: str) -> list[list[str]]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if header_needle in line and line.strip().startswith("|"):
            start = i
            break
    if start is None:
        return []
    rows: list[list[str]] = []
    for line in lines[start + 2 :]:
        if not line.strip().startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


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
        self.assertNotRegex(text, _VENDOR_RE)
        self.assertNotIn("GitLab-grade already achieved", text)
        self.assertIn("not the grade", lowered.replace("*", ""))
        self.assertIn("blank date or owner = fail", lowered)
        self.assertIn("unsigned / unnamed", lowered)

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
        joined = support + "\n" + deploy
        self.assertIn("internal-lab", joined)
        self.assertIn("soak_backup_upgrade_dry_run.py", joined)
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

    def test_unsigned_blank_date_owner_is_fail_not_auto_pass(self) -> None:
        """Unsigned / blank date-owner cannot auto-pass G9. Aegis lock."""
        text = _CHECKLIST.read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertIn("blank date or owner = fail", lowered)
        self.assertIn("unsigned / unnamed = **not** a gitlab-grade claim", lowered)

        named = {row[0].lower(): row[1] for row in _markdown_rows(text, "| Field | Value |") if len(row) >= 2}
        self.assertTrue(named, "named-pilot field table missing")
        owner = next((v for k, v in named.items() if "owner" in k), "")
        soak_start = next((v for k, v in named.items() if "soak start" in k), "")
        sign_off = next((v for k, v in named.items() if "sign-off" in k), "")
        signer = next((v for k, v in named.items() if k.startswith("signer")), "")
        unsigned = all(_placeholder(v) for v in (owner, soak_start, sign_off, signer))

        rows = _markdown_rows(text, "| # | Item | Pass / fail |")
        self.assertGreaterEqual(len(rows), 8, "G9 pass/fail rows missing")
        for row in rows:
            self.assertGreaterEqual(len(row), 5, row)
            status, date, owner_cell = row[2], row[3], row[4]
            if status.lower() == "pass":
                self.assertFalse(
                    _placeholder(date) or _placeholder(owner_cell),
                    f"blank date/owner cannot pass: {row}",
                )
            if unsigned:
                self.assertNotEqual(
                    status.lower(),
                    "pass",
                    "unsigned sheet cannot auto-pass a G9 row",
                )
        if unsigned:
            self.assertNotIn("gitlab-grade already achieved", lowered)

    def test_internal_lab_binder_links_checklist_and_dry_run(self) -> None:
        """Loom: binder is not an orphan — it points at soak + dry-run."""
        self.assertTrue(_BINDER.is_file(), f"missing {_BINDER.relative_to(_REPO)}")
        self.assertTrue(_DRY_RUN.is_file(), f"missing {_DRY_RUN.relative_to(_REPO)}")
        binder = _BINDER.read_text(encoding="utf-8")
        lowered = binder.lower()
        for needle in (
            "internal-lab",
            "pilot name",
            "owner",
            "soak",
            "production-install-soak-checklist.md",
            "soak_backup_upgrade_dry_run.py",
            "backup_restore_drill",
            "production-upgrade.md",
            "emit_only",
            "evaluate",
            "rust",
            "empty",
            "url",
        ):
            self.assertIn(needle, lowered if needle.islower() else binder.lower())
        self.assertNotRegex(binder, _VENDOR_RE)
        self.assertNotIn("GitLab-grade already achieved", binder)
        self.assertNotIn("published 1.3.0-beta", lowered)
        self.assertIn("not the grade", lowered.replace("*", ""))
        self.assertIn("out of scope", lowered)
        checklist = _CHECKLIST.read_text(encoding="utf-8")
        self.assertIn("docs/pilots/internal-lab", checklist)
        self.assertIn("soak_backup_upgrade_dry_run.py", checklist)
        for src, rel in (
            (_CHECKLIST, "../../pilots/internal-lab/README.md"),
            (_DEPLOY, "../../pilots/internal-lab/README.md"),
            (_BINDER, "../../docs/guides/production-install-soak-checklist.md"),
            (_BINDER, "../../../scripts/oss/soak_backup_upgrade_dry_run.py"),
        ):
            self.assertIn(rel, src.read_text(encoding="utf-8"), f"{src.name} must link {rel}")
            target = (src.parent / rel).resolve()
            self.assertTrue(target.is_file(), f"broken link from {src.name}: {rel} -> {target}")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
