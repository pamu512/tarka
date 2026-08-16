#!/usr/bin/env python3
"""SAR transport fails closed when SFTP host is unset. Calls the function, not source text."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    sys.path.insert(0, str(_REPO / "services" / "case-api" / "src"))
    os.environ.pop("FINCEN_BSA_SFTP_HOST", None)

    from case_api.sar_filing_transport import build_sftp_destination

    errors: list[str] = []
    if build_sftp_destination() is not None:
        errors.append("build_sftp_destination() must be None without FINCEN_BSA_SFTP_HOST")
    os.environ["FINCEN_BSA_SFTP_HOST"] = "  "
    if build_sftp_destination() is not None:
        errors.append("whitespace-only FINCEN_BSA_SFTP_HOST must be None")
    os.environ["FINCEN_BSA_SFTP_HOST"] = "sftp.example.test"
    if build_sftp_destination() != "sftp.example.test":
        errors.append("build_sftp_destination() must return the stripped host")

    if errors:
        print("sar_transport_honesty_smoke: FAIL", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("sar_transport_honesty_smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
