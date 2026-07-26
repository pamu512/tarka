#!/usr/bin/env python3
"""Assert an env file meets production fail-closed auth/idempotency policy.

Usage:
  python3 scripts/release/assert_production_profile.py \\
    --env-file infra/deploy/release/fixtures/production-profile.ok.env

  python3 scripts/release/assert_production_profile.py \\
    --env-file infra/deploy/release/fixtures/production-profile.bad.env --expect-fail
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_DEC_SRC = ROOT / "services" / "decision-api" / "src"
if str(_DEC_SRC) not in sys.path:
    sys.path.insert(0, str(_DEC_SRC))

from decision_api.production_profile import check_production_env  # noqa: E402


def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument(
        "--expect-fail",
        action="store_true",
        help="Exit 0 only when checks fail (negative fixture)",
    )
    args = p.parse_args()
    if not args.env_file.is_file():
        print(f"FAIL: env file not found: {args.env_file}", file=sys.stderr)
        return 2
    errors = check_production_env(_load_env_file(args.env_file))
    if args.expect_fail:
        if errors:
            print(f"OK: expected failures ({len(errors)}):")
            for e in errors:
                print(f"  - {e}")
            return 0
        print("FAIL: expected production checks to fail, but they passed", file=sys.stderr)
        return 1
    if errors:
        print("FAIL: production profile checks:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"OK: production profile checks passed ({args.env_file})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
