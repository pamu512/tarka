#!/usr/bin/env python3
"""Create GitHub issues for v1.3.0 Wave 1 — Q1-E04 and Q1-E08 (Reliability Gate).

Requires: gh CLI authenticated (`gh auth login`).

Usage:
  python3 scripts/github/create_v130_wave1_q1_child_issues.py --dry-run
  python3 scripts/github/create_v130_wave1_q1_child_issues.py

Re-run safety: always creates new issues; use --dry-run first.
Umbrella epics: Q1-E04 #130, Q1-E08 #134.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

REPO = "pamu512/tarka"
MILESTONE = "Q1-2026"

WAVE_1_EPICS = [
    {
        "epic_id": "Q1-E04",
        "parent": 130,
        "title": "[Q1-E04] Service health and SLO burn operationalization",
        "labels": ["wave-1", "reliability-gate", "epic:q1-e04"],
        "body": """### Acceptance Criteria
- [ ] Add `runbook_url` and `severity` annotations to `infra/deploy/observability/prometheus-rules/slo-burn.yml` pointing to `docs/docs/operations/slo-burn-response.md`.
- [ ] Extend burn rules to missing Helm services: `event-ingest`, `graphql-gateway`, `investigation-agent`, `analytics-sink`.
- [ ] Update `docs/docs/guides/service-slos-v1.md` with Alertmanager routing + on-call mapping.

### Quarter-Gate Evidence (Reliability Gate)
**Gate:** SLO burn alerts wired to active runbooks
- [ ] Verify: `GET /v1/slo` returns covered services.
- [ ] Verify: Prometheus rule lint passes.
- [ ] Verify: Manual alert annotation spot-check succeeds.

*Attach evidence screenshots or CI run links below before closing:*
>

### PR Links
- #PR_NUMBER_HERE
""",
    },
    {
        "epic_id": "Q1-E08",
        "parent": 134,
        "title": "[Q1-E08] Runbook pack for fallback and emergency ops",
        "labels": ["wave-1", "reliability-gate", "epic:q1-e08"],
        "body": """### Acceptance Criteria
- [ ] Create `docs/docs/operations/runbook-pack-index.md` consolidating:
  - `docs/docs/guides/fallback-emergency-runbook.md`
  - `docs/docs/operations/runbook-common-failures.md`
  - `docs/docs/guides/counter-replay-parity.md`
  - `docs/docs/guides/runbook-chaos-template.md`
  - `docs/docs/operations/slo-burn-response.md` (from E04)
- [ ] Cross-link index from `infra/deploy/observability/grafana/provisioning/dashboards/json/tarka-slo-burn.json`.

### Quarter-Gate Evidence (Reliability Gate)
**Gate:** Alerts wired to active runbooks
- [ ] Verify: Every slo-burn alert resolves to an indexed runbook URL.

*Attach evidence screenshots or CI run links below before closing:*
>

### PR Links
- #PR_NUMBER_HERE
""",
    },
]


def create_issues(*, dry_run: bool = False) -> None:
    print("Generating Wave 1 issues for v1.3.0...")
    created: list[tuple[str, str]] = []

    for epic in WAVE_1_EPICS:
        cmd = [
            "gh",
            "issue",
            "create",
            "-R",
            REPO,
            "--title",
            epic["title"],
            "--body",
            epic["body"],
            "--milestone",
            MILESTONE,
        ]
        for label in epic["labels"]:
            cmd.extend(["--label", label])

        if dry_run:
            print(f"\n---\nTITLE: {epic['title']}\nLABELS: {epic['labels']}\n")
            print(epic["body"])
            continue

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            url = result.stdout.strip()
            print(f"Created: {url}")
            num = url.rstrip("/").split("/")[-1]
            created.append((epic["epic_id"], num))
        except FileNotFoundError:
            print("GitHub CLI (gh) not found. Please install it or authenticate.", file=sys.stderr)
            sys.exit(1)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to create issue: {epic['title']}\n{exc.stderr}", file=sys.stderr)
            sys.exit(exc.returncode)

    if dry_run:
        print(f"\nDry run: would create {len(WAVE_1_EPICS)} issue(s).")
        return

    if created:
        print("\nLink on umbrella issues:")
        for epic_id, num in created:
            parent = next(e["parent"] for e in WAVE_1_EPICS if e["epic_id"] == epic_id)
            print(f"  {epic_id} #{parent}: - [ ] #{num}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create v1.3.0 Wave 1 issues (Q1-E04, Q1-E08)")
    parser.add_argument("--dry-run", action="store_true", help="Print issue bodies; do not call gh")
    args = parser.parse_args()
    create_issues(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
