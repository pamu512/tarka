#!/usr/bin/env python3
"""CI contract for SoR backup/restore guide + drill (G6)."""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "infra" / "scripts" / "deploy" / "backup_restore_drill.sh"
_GUIDE = _REPO / "docs" / "docs" / "guides" / "production-backup-restore.md"
_DEPLOY = _REPO / "docs" / "docs" / "guides" / "deployment.md"
_PRESET = (
    _REPO
    / "infra"
    / "deploy"
    / "helm"
    / "fraud-stack"
    / "presets"
    / "enterprise-desk-on-k8s.yaml"
)


class TestBackupRestoreDrill(unittest.TestCase):
    def test_guide_covers_sor_redis_age_and_not_saas(self) -> None:
        self.assertTrue(_GUIDE.is_file(), f"missing {_GUIDE.relative_to(_REPO)}")
        text = _GUIDE.read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertIn("decision_audit", text)
        self.assertIn("rule_approvals", text)
        self.assertIn("investigation_label_drafts", text)
        self.assertIn("leftover_promote_acks", text)
        self.assertIn("Redis", text)
        self.assertIn("ephemeral", lowered)
        self.assertIn("AGE", text)
        self.assertIn("volume", lowered)
        self.assertIn("pg_dump", text)
        self.assertIn("RPO", text)
        self.assertIn("RTO", text)
        self.assertIn("tenant policy", lowered)
        self.assertIn("not", lowered)
        self.assertIn("enterprise-desk", text)
        self.assertIn("age_restore_drill.sh", text)
        self.assertIn("DECISION_LOG_PATH", text)
        self.assertIn("python3", text)
        self.assertIn("empty of SoR tables", text)
        self.assertNotIn("the script can exec client tools from", text)
        self.assertTrue(
            "not a sla" in lowered or "not slas" in lowered or "not commitments" in lowered,
            "RPO/RTO must be tenant policy examples, not SLAs",
        )
        self.assertTrue(
            "hosted backup" in lowered or "backup saas" in lowered or "operated backup" in lowered
        )
        self.assertIn("Out of scope", text)

    def test_deployment_links_guide(self) -> None:
        text = _DEPLOY.read_text(encoding="utf-8")
        self.assertIn("production-backup-restore.md", text)

    def test_enterprise_desk_preset_points_at_age_volume_restore(self) -> None:
        text = _PRESET.read_text(encoding="utf-8")
        self.assertIn("age_restore_drill.sh", text)
        self.assertIn("volume", text.lower())
        self.assertIn("pg_dump", text.lower())

    def test_script_exists_and_executable_contract(self) -> None:
        self.assertTrue(_SCRIPT.is_file(), f"missing {_SCRIPT}")
        self.assertTrue(os.access(_SCRIPT, os.X_OK), f"not executable: {_SCRIPT}")
        text = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--dry-run", text)
        self.assertIn("--docker-smoke", text)
        self.assertIn("--live", text)
        self.assertIn("decision_audit", text)
        self.assertIn("I_UNDERSTAND", text)
        self.assertIn("age_restore_drill.sh", text)
        self.assertIn("ephemeral", text.lower())
        # Live must refuse same-URL restore. AGE Hunt is not dumped here.
        self.assertIn("fingerprint", text)
        self.assertIn("scratch already has SoR tables", text)
        self.assertIn("same path as --live", text)
        self.assertIn("./data/decision_logs/decision-log.jsonl", text)
        self.assertIn("./rules/_loop/promote_export.jsonl", text)
        self.assertNotRegex(text, r"(?m)^\s*pg_dump\b.*age")

    def test_dry_run_exits_zero_without_database(self) -> None:
        env = os.environ.copy()
        env.pop("DATABASE_URL", None)
        env.pop("TARKA_BACKUP_DRILL_SKIP", None)
        r = subprocess.run(
            ["bash", str(_SCRIPT), "--dry-run"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("dry-run OK", r.stdout)
        self.assertIn("ephemeral", r.stdout.lower())

    def test_live_refuses_without_confirm(self) -> None:
        env = os.environ.copy()
        env.pop("TARKA_BACKUP_RESTORE_CONFIRM", None)
        env["DATABASE_URL"] = "postgresql://fraud:fraud@localhost:5432/fraud"
        env["TARKA_BACKUP_RESTORE_URL"] = "postgresql://fraud:fraud@localhost:5432/scratch"
        r = subprocess.run(
            ["bash", str(_SCRIPT), "--live"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("I_UNDERSTAND", r.stderr)

    def test_live_refuses_same_fingerprint(self) -> None:
        env = os.environ.copy()
        env["TARKA_BACKUP_RESTORE_CONFIRM"] = "I_UNDERSTAND"
        env["DATABASE_URL"] = "postgresql+asyncpg://a:b@rds.internal:5432/fraud"
        env["TARKA_BACKUP_RESTORE_URL"] = "postgresql://c:d@rds.internal:5432/fraud"
        r = subprocess.run(
            ["bash", str(_SCRIPT), "--live"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refuse", r.stderr.lower())

    def test_docker_smoke_when_opted_in(self) -> None:
        if os.environ.get("TARKA_BACKUP_DRILL_SKIP") == "1":
            self.skipTest("TARKA_BACKUP_DRILL_SKIP=1")
        if shutil.which("docker") is None:
            self.skipTest("docker not available")
        if os.environ.get("TARKA_BACKUP_DRILL_RUN") != "1":
            self.skipTest("set TARKA_BACKUP_DRILL_RUN=1 to execute docker smoke")
        r = subprocess.run(
            ["bash", str(_SCRIPT), "--docker-smoke"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("SoR backup/restore docker-smoke OK", r.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
