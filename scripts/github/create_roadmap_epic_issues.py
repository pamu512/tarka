#!/usr/bin/env python3
from __future__ import annotations

"""Create umbrella GitHub issues for docs/docs/guides/tarka-12-month-roadmap-execution-kit.md epics.

Requires: gh CLI, authenticated (gh auth login).

Usage:
  python3 scripts/github/create_roadmap_epic_issues.py           # create all epics
  python3 scripts/github/create_roadmap_epic_issues.py --dry-run # print gh commands only

Re-run safety: always creates new issues; do not run twice unless you want duplicates.
"""


import argparse
import subprocess
import sys

REPO = "pamu512/tarka"
DOC_PATH = "docs/docs/guides/tarka-12-month-roadmap-execution-kit.md"
DOC_URL = f"https://github.com/{REPO}/blob/master/{DOC_PATH}"

TAG_TO_LABEL = {
    "SEC": "area/security",
    "PLAT": "area/platform",
    "DATA": "area/data",
    "UX": "area/ux",
    "GRAPH": "area/graph",
    "AI": "area/ai-copilot",
    "SRE": "area/sre",
    "COMP": "area/compliance",
}

# (epic_id, title, size, space_separated_tags, milestone_title)
EPICS: list[tuple[str, str, str, str, str]] = [
    # Q1
    ("Q1-E01", "Policy-as-code baseline for default deployments", "M", "SEC PLAT COMP", "Q1-2026"),
    ("Q1-E02", "Tenant binding enforcement rollout and migration aids", "M", "SEC DATA", "Q1-2026"),
    ("Q1-E03", "Preset and overlay promotion framework", "M", "PLAT SRE", "Q1-2026"),
    ("Q1-E04", "Service health/SLO burn operationalization", "S", "SRE PLAT", "Q1-2026"),
    ("Q1-E05", "Analyst error and degraded-mode UX baseline", "M", "UX AI", "Q1-2026"),
    ("Q1-E06", "Release-readiness sign-off automation", "S", "COMP SRE", "Q1-2026"),
    ("Q1-E07", "Environment parity and config contract tests", "M", "PLAT SEC", "Q1-2026"),
    ("Q1-E08", "Runbook pack for fallback and emergency ops", "S", "SRE COMP", "Q1-2026"),
    # Q2
    ("Q2-E01", "Unified analyst workbench composition", "L", "UX AI GRAPH", "Q2-2026"),
    ("Q2-E02", "Copilot confidence and citation quality framework", "M", "AI COMP", "Q2-2026"),
    ("Q2-E03", "Graph explainability and path reasoning surfaces", "M", "GRAPH UX", "Q2-2026"),
    ("Q2-E04", "Entity resolution confidence and analyst override loop", "M", "GRAPH DATA", "Q2-2026"),
    ("Q2-E05", "Drift and benchmark analytics dashboards", "M", "DATA AI SRE", "Q2-2026"),
    ("Q2-E06", "Counter catalog and operator transparency API/UI", "S", "DATA UX", "Q2-2026"),
    ("Q2-E07", "Cross-workflow navigation and state continuity", "S", "UX", "Q2-2026"),
    ("Q2-E08", "Collaboration bridge bidirectional case actions", "M", "AI PLAT", "Q2-2026"),
    # Q3
    ("Q3-E01", "Rule/model/policy bundle promotion workflow", "L", "DATA COMP SEC", "Q3-2026"),
    ("Q3-E02", "Offline-online parity and lineage registry", "L", "DATA AI", "Q3-2026"),
    ("Q3-E03", "Queue backpressure and ingest resiliency suite", "M", "SRE PLAT", "Q3-2026"),
    ("Q3-E04", "DR rehearsal automation and scorecards", "M", "SRE COMP", "Q3-2026"),
    ("Q3-E05", "Compliance evidence auto-pack generation", "M", "COMP SEC", "Q3-2026"),
    ("Q3-E06", "Experiment governance (holdout, sample-size warnings)", "M", "DATA AI", "Q3-2026"),
    ("Q3-E07", "Secrets rotation and service identity hardening", "M", "SEC PLAT", "Q3-2026"),
    # Q4
    ("Q4-E01", "Progressive delivery (canary/blue-green) toolkit", "L", "PLAT SRE", "Q4-2026"),
    ("Q4-E02", "Connector SDK and partner certification profile", "M", "PLAT DATA", "Q4-2026"),
    ("Q4-E03", "External evidence ingestion normalization", "M", "DATA COMP", "Q4-2026"),
    ("Q4-E04", "Executive trust and compliance analytics pack", "M", "DATA UX", "Q4-2026"),
    ("Q4-E05", "Copilot persona and policy-controlled action framework", "M", "AI SEC", "Q4-2026"),
    ("Q4-E06", "Tenant-safe benchmarking and cohort exports", "M", "DATA COMP", "Q4-2026"),
    ("Q4-E07", "Flight-recorder diagnostics for hosted/self-hosted support", "S", "SRE PLAT", "Q4-2026"),
]


def body(epic_id: str, title: str, size: str, tags: list[str]) -> str:
    tags_line = ", ".join(tags)
    return f"""## Umbrella epic

**Epic ID:** `{epic_id}`
**Title:** {title}
**Size:** {size} (see execution kit for sizing key)
**Dependency tags:** {tags_line}

## Narrative source of truth

This epic tracks work described in the repo doc (sections *Quarterly Backlog* and related):

- [{DOC_PATH}]({DOC_URL})

## How to use this issue

- This is an **umbrella** epic: break work into **child issues** with clear acceptance criteria.
- Apply **`good first issue`** only to small, well-scoped child issues (not this umbrella).
- Link child issues in comments or a checklist below.

### Child issues

- [ ] (add sub-issues here)

## Acceptance (epic level)

Epic is done when outcomes in the execution kit for this row are met and any quarter gate criteria for the milestone are satisfied.
"""


def gh_issue_create(
    *,
    title: str,
    body_md: str,
    labels: list[str],
    milestone: str,
    dry_run: bool,
) -> str | None:
    cmd = [
        "gh",
        "issue",
        "create",
        "-R",
        REPO,
        "--title",
        title,
        "--body",
        body_md,
        "--milestone",
        milestone,
    ]
    for lab in labels:
        cmd.extend(["--label", lab])
    if dry_run:
        print(" ".join(cmd[:6] + ["...", f"({len(labels)} labels)"]))
        return None
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(r.returncode)
    # gh prints URL on success
    url = (r.stdout or "").strip()
    return url or None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    created: list[tuple[str, str]] = []
    for epic_id, title, size, tag_str, milestone in EPICS:
        tags = tag_str.split()
        labels = ["roadmap", "help wanted"] + sorted({TAG_TO_LABEL[t] for t in tags})
        gh_title = f"[Roadmap] {epic_id}: {title}"
        b = body(epic_id, title, size, tags)
        url = gh_issue_create(
            title=gh_title,
            body_md=b,
            labels=labels,
            milestone=milestone,
            dry_run=args.dry_run,
        )
        if url:
            num = url.rstrip("/").split("/")[-1]
            created.append((epic_id, num))

    if not args.dry_run:
        print("Created issues:")
        for epic_id, num in created:
            print(f"  {epic_id}: #{num} https://github.com/{REPO}/issues/{num}")


if __name__ == "__main__":
    main()
