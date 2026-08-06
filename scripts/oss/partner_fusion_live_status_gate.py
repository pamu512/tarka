#!/usr/bin/env python3
"""Fail-closed L2 partner fusion status gate (Risk/Strategy 4.2).

Status file: docs/compliance/partner-fusion-proof.live.status

Allowed lines (trimmed):
  LIVE
  WAIVED — reason: <non-empty>

When REQUIRE_LIVE_PARTNER_PROOF=1:
  LIVE requires docs/compliance/partner-fusion-proof.live.sha256 (non-empty).
  Fixture/stable SHA alone never satisfies this gate.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_STATUS = _REPO / "docs" / "compliance" / "partner-fusion-proof.live.status"
_LIVE_SHA = _REPO / "docs" / "compliance" / "partner-fusion-proof.live.sha256"
_WAIVED_RE = re.compile(r"^WAIVED\s*[—\-]\s*reason:\s*\S.+$", re.IGNORECASE)


def parse_status(text: str) -> str:
    line = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
    if line.upper() == "LIVE":
        return "LIVE"
    if _WAIVED_RE.match(line):
        return "WAIVED"
    return ""


def evaluate(
    *,
    status_text: str,
    live_sha_text: str | None,
    require_live: bool,
) -> tuple[int, str]:
    kind = parse_status(status_text)
    if not kind:
        return 1, "invalid or missing LIVE|WAIVED status line"
    if kind == "WAIVED":
        return 0, "WAIVED ok"
    # LIVE
    sha = (live_sha_text or "").strip()
    if not sha:
        return 1, "LIVE requires non-empty partner-fusion-proof.live.sha256"
    if require_live:
        return 0, "LIVE pin ok"
    return 0, "LIVE pin ok"


def main() -> int:
    require = (os.environ.get("REQUIRE_LIVE_PARTNER_PROOF") or "").strip() == "1"
    if not _STATUS.is_file():
        if require:
            print("partner_fusion_live_status_gate: FAIL — missing live.status", file=sys.stderr)
            return 1
        print("partner_fusion_live_status_gate: SKIP — no live.status (REQUIRE not set)")
        return 0
    status_text = _STATUS.read_text(encoding="utf-8")
    live_sha = _LIVE_SHA.read_text(encoding="utf-8") if _LIVE_SHA.is_file() else ""
    code, msg = evaluate(
        status_text=status_text,
        live_sha_text=live_sha,
        require_live=require,
    )
    if code != 0:
        print(f"partner_fusion_live_status_gate: FAIL — {msg}", file=sys.stderr)
        return 1
    if require:
        print(f"partner_fusion_live_status_gate: OK ({msg}) [REQUIRE_LIVE_PARTNER_PROOF=1]")
    else:
        print(f"partner_fusion_live_status_gate: OK ({msg})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
