"""Regression test: third-party GitHub Actions in non-ci.yml workflows must be
SHA-pinned (40-hex-char ref), not tag-pinned.

GitHub-owned actions (actions/*, github/*) are exempt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS_DIR = Path(__file__).resolve().parents[3] / ".github" / "workflows"
SKIP_FILES = {"ci.yml"}

# GitHub-owned orgs whose actions we allow to stay tag-pinned.
GITHUB_OWNED_PREFIXES = ("actions/", "github/")

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_USES_RE = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)", re.MULTILINE)


def _collect_violations() -> list[str]:
    violations: list[str] = []
    for wf in sorted(WORKFLOWS_DIR.glob("*.yml")):
        if wf.name in SKIP_FILES:
            continue
        text = wf.read_text()
        for m in _USES_RE.finditer(text):
            ref = m.group("ref")
            if ref.startswith("./"):
                continue
            if any(ref.startswith(p) for p in GITHUB_OWNED_PREFIXES):
                continue
            # ref looks like owner/action@version_or_sha
            if "@" not in ref:
                continue
            _, pin = ref.rsplit("@", 1)
            # Strip trailing inline comment if attached (shouldn't be, but safe)
            pin = pin.split("#")[0].strip()
            if not _SHA_RE.match(pin):
                line_no = text[: m.start()].count("\n") + 1
                violations.append(f"{wf.name}:{line_no}  {ref}")
    return violations


def test_third_party_actions_are_sha_pinned():
    violations = _collect_violations()
    assert violations == [], (
        "Third-party GitHub Actions must be pinned to a full 40-char commit SHA "
        "(uses: owner/action@<sha> # vX.Y.Z).  Violations:\n"
        + "\n".join(f"  {v}" for v in violations)
    )
