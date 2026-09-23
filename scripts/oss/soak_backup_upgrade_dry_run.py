#!/usr/bin/env python3
"""Named-pilot G9 soak start: date G6 backup + G7 upgrade dry-runs.

Requires --pilot-name --owner --date. Blank owner or date exits non-zero.
Calls the existing SoR backup drill (--dry-run) and docs-links the G7
upgrade runbook. Does not sign G9, apply Helm to a cluster, or publish a tag.

Usage (repo root)::

  python3 scripts/oss/soak_backup_upgrade_dry_run.py \\
    --pilot-name internal-lab --owner <operator> --date <UTC>
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_BACKUP_DRILL = _REPO / "infra" / "scripts" / "deploy" / "backup_restore_drill.sh"
_BACKUP_GUIDE = "docs/docs/guides/production-backup-restore.md"
_UPGRADE_GUIDE = "docs/docs/guides/production-upgrade.md"
_UPGRADE_CI = "infra/scripts/ci/test_helm_upgrade_dry_run.py"
_CHECKLIST = "docs/docs/guides/production-install-soak-checklist.md"
_BINDER = "docs/pilots/internal-lab/README.md"


def _blank(value: str | None) -> bool:
    token = (value or "").strip()
    if not token:
        return True
    if set(token) <= {"_"}:
        return True
    return False


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Date a named-pilot G6 backup + G7 upgrade dry-run (not a G9 sign-off)."
    )
    parser.add_argument("--pilot-name", required=True, help="Named pilot (internal-lab is valid).")
    parser.add_argument("--owner", required=True, help="Operator / owner. Blank is fail.")
    parser.add_argument("--date", required=True, help="Soak / evidence date (UTC). Blank is fail.")
    return parser.parse_args(argv)


def _refuse_blank(pilot_name: str, owner: str, date: str) -> str | None:
    if _blank(pilot_name):
        return "pilot-name is blank"
    if _blank(owner):
        return "owner is blank"
    if _blank(date):
        return "date is blank"
    return None


def _run_backup_dry_run() -> tuple[int, str]:
    if not _BACKUP_DRILL.is_file():
        return 1, f"missing {_BACKUP_DRILL.relative_to(_REPO)}"
    env = os.environ.copy()
    # Soak dating must actually run the drill. Skip env is not evidence.
    env.pop("TARKA_BACKUP_DRILL_SKIP", None)
    env.pop("DATABASE_URL", None)
    result = subprocess.run(
        ["bash", str(_BACKUP_DRILL), "--dry-run"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    return result.returncode, combined


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    reason = _refuse_blank(args.pilot_name, args.owner, args.date)
    if reason:
        print(f"refuse: {reason} (Aegis: owner or date blank = fail)", file=sys.stderr)
        return 2

    print("=== G9 soak start dry-run (not a grade claim) ===")
    print(f"pilot_name: {args.pilot_name.strip()}")
    print(f"owner: {args.owner.strip()}")
    print(f"date: {args.date.strip()}")
    print("signed: no")
    print("gitlab_grade_claim: no")
    print(f"soak_checklist: {_CHECKLIST}")
    print(f"binder: {_BINDER}")
    print("locks: evaluate=Rust; enforcement.mode=emit_only; empty URL = plane off")
    print()

    print("--- G6 backup dry-run ---")
    print(f"runbook: {_BACKUP_GUIDE}")
    print("script: infra/scripts/deploy/backup_restore_drill.sh --dry-run")
    code, backup_out = _run_backup_dry_run()
    sys.stdout.write(backup_out)
    if not backup_out.endswith("\n"):
        print()
    if code != 0:
        print(f"G6 backup dry-run failed (exit {code})", file=sys.stderr)
        return code if code != 0 else 1
    print(f"G6 backup dry-run dated {args.date.strip()} by {args.owner.strip()} for pilot {args.pilot_name.strip()}")
    print()

    print("--- G7 upgrade dry-run ---")
    print(f"runbook: {_UPGRADE_GUIDE}")
    print(f"ci_contract: {_UPGRADE_CI}")
    print("operator: helm template of the to-pin on the cluster host; no helm apply here")
    print("no cluster helm apply in this script (CI-safe)")
    print(f"G7 upgrade dry-run dated {args.date.strip()} by {args.owner.strip()} for pilot {args.pilot_name.strip()}")
    print()
    print("evidence recorded on stdout only. Fill the G9 checklist rows with this date/owner.")
    print("This script does not sign G9 and does not publish 1.3.0-beta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
