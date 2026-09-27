#!/usr/bin/env python3
"""Signal-catalog drift gate (P3.3 companion).

docs/docs/guides/signal-catalog.md is hand-written and declares: "a drifted
row is a bug". This gate enforces it for the behavior-tag table - every tag
the pipeline can mint must appear in the doc, and every behavior:* tag the doc
names must be mintable by extract_behavior_tags (no aspirational rows).

Run: python3 infra/scripts/ci/check_signal_catalog.py
Exit 0 = catalog in sync. Exit 1 = drift, printed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "docs" / "guides" / "signal-catalog.md"
SRC = REPO / "services" / "decision-api" / "src"

DOC_TAG_RE = re.compile(r"`(behavior:[a-z_]+)`")
SRC_TAG_RE = re.compile(r'"(behavior:[a-z_]+)"')


def mintable_tags() -> set[str]:
    """Collect every behavior:* tag literal in extract_behavior_tags."""
    text = (SRC / "decision_api" / "main.py").read_text(encoding="utf-8")
    m = re.search(r"def extract_behavior_tags.*?(?=\ndef |\nclass |\Z)", text, re.DOTALL)
    if not m:
        raise SystemExit("check_signal_catalog: extract_behavior_tags not found")
    return set(SRC_TAG_RE.findall(m.group(0)))


def documented_tags() -> set[str]:
    text = DOC.read_text(encoding="utf-8")
    m = re.search(r"## Behavior signals.*?(?=\n## )", text, re.DOTALL)
    if not m:
        raise SystemExit("check-catalog: signal-catalog.md has no Behavior signals section")
    return set(DOC_TAG_RE.findall(m.group(0)))


def main() -> int:
    mintable = mintable_tags()
    documented = documented_tags()

    missing = sorted(mintable - documented)
    aspirational = sorted(documented - mintable)

    ok = True
    if missing:
        ok = False
        print("signal-catalog drift: tags mintable but NOT documented (add rows):")
        for t in missing:
            print(f"  - {t}")
    if aspirational:
        ok = False
        print("signal-catalog drift: tags documented but NOT mintable (remove rows):")
        for t in aspirational:
            print(f"  - {t}")
    if ok:
        print(f"signal catalog: OK ({len(documented)} behavior tags in sync)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
