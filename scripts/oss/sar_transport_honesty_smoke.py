#!/usr/bin/env python3
"""Missed-mark bridge A3: SAR transport fails closed when SFTP is unset."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    main_py = (
        _REPO / "services" / "case-api" / "src" / "case_api" / "main.py"
    ).read_text(encoding="utf-8")
    transport = (
        _REPO
        / "services"
        / "case-api"
        / "src"
        / "case_api"
        / "sar_filing_transport.py"
    ).read_text(encoding="utf-8")
    worker = (
        _REPO
        / "services"
        / "case-api"
        / "src"
        / "case_api"
        / "sar_transport_worker.py"
    )

    errors: list[str] = []
    if "SFTP_TRANSPORT_NOT_CONFIGURED" not in main_py:
        errors.append("main.py missing SFTP_TRANSPORT_NOT_CONFIGURED fail-closed reason")
    if "FINCEN_BSA_SFTP_HOST" not in transport and "FINCEN_BSA_SFTP_HOST" not in main_py:
        errors.append("FINCEN_BSA_SFTP_HOST not referenced")
    if "SAR_FAILED" not in main_py and "FAILED" not in main_py:
        errors.append("expected FAILED status when SFTP unset")
    # Ensure we do not leave intents pending when host unset (honest path sets FAILED)
    if "Awaiting compliance approval" in main_py and "SFTP_TRANSPORT_NOT_CONFIGURED" not in main_py:
        errors.append("pending-only path without fail-closed branch")
    if not worker.is_file():
        errors.append("sar_transport_worker.py missing")
    else:
        w = worker.read_text(encoding="utf-8")
        if "async def" not in w and "def " not in w:
            errors.append("sar_transport_worker.py looks empty")

    sys.path.insert(0, str(_REPO / "services" / "case-api" / "src"))
    try:
        from case_api.sar_filing_transport import build_sftp_destination  # type: ignore

        # With env unset, destination must be falsy
        import os

        os.environ.pop("FINCEN_BSA_SFTP_HOST", None)
        if build_sftp_destination():
            errors.append("build_sftp_destination() truthy without FINCEN_BSA_SFTP_HOST")
    except Exception as e:
        errors.append(f"import/build_sftp_destination failed: {e}")

    if errors:
        print("sar_transport_honesty_smoke: FAIL", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("sar_transport_honesty_smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
