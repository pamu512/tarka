#!/usr/bin/env python3
"""Fetch analytics-sink decision scorecard JSON and open a GitHub Discussion (OSS #53).

Environment (typical in GitHub Actions):
  SCORECARD_BASE_URL   Gateway base URL, e.g. https://example.com/api/analytics (no trailing slash)
  SCORECARD_API_KEY    Optional x-api-key for analytics-sink
  SCORECARD_TENANT_ID  Default: demo
  SCORECARD_DAYS       Default: 7
  DISCUSSION_CATEGORY  Category name (default: General)
  GITHUB_TOKEN         default Actions token (needs discussions: write)
  GITHUB_REPOSITORY    owner/name

Dry-run locally without GITHUB_TOKEN: prints Markdown only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def build_markdown(data: dict[str, Any]) -> str:
    tenant = str(data.get("tenant_id", ""))
    days = int(data.get("window_days", 0))
    total = int(data.get("total_events", 0))
    deny = float(data.get("deny_rate_pct", 0.0))
    lines = [
        f"## Decision scorecard — `{tenant}`",
        "",
        f"**Window:** {days} day(s) · **Total events:** {total:,} · **Deny rate:** {deny:.2f}%",
        "",
        "### Per decision",
        "",
        "| Decision | Count | % | Avg score |",
        "| --- | ---: | ---: | ---: |",
    ]
    for r in data.get("per_decision") or []:
        if not isinstance(r, dict):
            continue
        lines.append(
            "| {decision} | {event_count} | {event_pct} | {avg:.1f} |".format(
                decision=r.get("decision", ""),
                event_count=r.get("event_count", ""),
                event_pct=r.get("event_pct", ""),
                avg=float(r.get("avg_score", 0.0)),
            )
        )
    lines.extend(["", "### Top rule hits", ""])
    rules = data.get("top_rule_hits") or []
    if not rules:
        lines.append("_No rule hits in window._")
    else:
        lines.extend(["| Rule | Hits |", "| --- | ---: |"])
        for raw in rules:
            if not isinstance(raw, dict):
                continue
            rid = str(raw.get("rule_id", ""))
            hits = raw.get("hit_count", "")
            lines.append(f"| `{rid or '—'}` | {hits} |")
    sha = (os.environ.get("GITHUB_SHA") or "")[:7]
    run_url = os.environ.get("GITHUB_SERVER_URL", "")
    lines.extend(
        [
            "",
            "---",
            "_Published by `scripts/analytics/publish_scorecard_discussion.py`" + (f" · {run_url}" if run_url else "") + (f" · `{sha}`" if sha else "") + "_",
        ]
    )
    return "\n".join(lines)


def fetch_scorecard(url: str, api_key: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if api_key:
        req.add_header("x-api-key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} from scorecard URL: {body[:800]}") from None


def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        out = json.loads(resp.read().decode())
    if out.get("errors"):
        raise SystemExit(f"GraphQL errors: {out['errors']}")
    return out["data"]


def resolve_repo_and_category(token: str, owner: str, name: str, category_name: str) -> tuple[str, str]:
    q = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        id
        discussionCategories(first: 30) {
          nodes { id name }
        }
      }
    }
    """
    data = graphql(token, q, {"owner": owner, "name": name})
    repo = data.get("repository")
    if not repo:
        raise SystemExit("Repository not found or token lacks access")
    rid = repo["id"]
    nodes = (repo.get("discussionCategories") or {}).get("nodes") or []
    want = category_name.strip().lower()
    cat_id = ""
    for n in nodes:
        if str(n.get("name", "")).strip().lower() == want:
            cat_id = str(n["id"])
            break
    if not cat_id and nodes:
        cat_id = str(nodes[0]["id"])
    if not cat_id:
        raise SystemExit("No discussion categories — enable Discussions on the repository")
    return str(rid), cat_id


def create_discussion(token: str, repo_id: str, category_id: str, title: str, body: str) -> str:
    m = """
    mutation($repositoryId: ID!, $categoryId: ID!, $title: String!, $body: String!) {
      createDiscussion(input: {repositoryId: $repositoryId, categoryId: $categoryId, title: $title, body: $body}) {
        discussion { url }
      }
    }
    """
    data = graphql(
        token,
        m,
        {"repositoryId": repo_id, "categoryId": category_id, "title": title, "body": body},
    )
    disc = (data.get("createDiscussion") or {}).get("discussion") or {}
    url = disc.get("url", "")
    if not url:
        raise SystemExit(f"Unexpected GraphQL response: {data!r}")
    return str(url)


def main() -> int:
    p = argparse.ArgumentParser(description="Publish decision scorecard to GitHub Discussions.")
    p.add_argument("--base-url", default=os.environ.get("SCORECARD_BASE_URL", "").rstrip("/"))
    p.add_argument("--tenant-id", default=os.environ.get("SCORECARD_TENANT_ID", "demo"))
    p.add_argument("--days", type=int, default=int(os.environ.get("SCORECARD_DAYS", "7")))
    p.add_argument("--api-key", default=os.environ.get("SCORECARD_API_KEY", ""))
    p.add_argument("--discussion-category", default=os.environ.get("DISCUSSION_CATEGORY", "General"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.base_url:
        print("SCORECARD_BASE_URL not set — nothing to do.", file=sys.stderr)
        return 0

    q = urllib.parse.urlencode({"tenant_id": args.tenant_id, "days": str(args.days)})
    score_url = f"{args.base_url}/v1/analytics/scorecard?{q}"
    payload = fetch_scorecard(score_url, args.api_key)
    body_md = build_markdown(payload)

    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    repo_full = (os.environ.get("GITHUB_REPOSITORY") or "").strip()

    if args.dry_run or not token or not repo_full:
        print(body_md)
        if not args.dry_run:
            print("(Set GITHUB_TOKEN and GITHUB_REPOSITORY to publish.)", file=sys.stderr)
        return 0

    parts = repo_full.split("/", 1)
    if len(parts) != 2:
        raise SystemExit("GITHUB_REPOSITORY must be owner/name")
    owner, name = parts
    rid, cid = resolve_repo_and_category(token, owner, name, args.discussion_category)
    title = f"Weekly decision scorecard — {payload.get('tenant_id', args.tenant_id)} ({args.days}d)"
    url = create_discussion(token, rid, cid, title, body_md)
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
