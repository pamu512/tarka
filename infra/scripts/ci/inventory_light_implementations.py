#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

"""Inventory lightweight implementations and emit a hardening matrix.

Usage:
  python infra/scripts/ci/inventory_light_implementations.py
  python infra/scripts/ci/inventory_light_implementations.py --json
  python infra/scripts/ci/inventory_light_implementations.py --write docs/docs/guides/light-implementation-hardening-inventory.md
"""


@dataclass(frozen=True)
class Rule:
    component: str
    owner: str
    priority: str
    path_glob: str
    pattern: str
    rationale: str
    hardening_hint: str


RULES: tuple[Rule, ...] = (
    Rule(
        component="Saarthi copilot LLM fallback",
        owner="services/investigation-agent",
        priority="P0",
        path_glob="services/investigation-agent/src/investigation_agent/main.py",
        pattern=r"\[offline mode\]|OPENAI_API_KEY",
        rationale="Offline branches change assistant behavior and can hide capability gaps.",
        hardening_hint="Expose structured degraded metadata and deterministic fallback artifacts.",
    ),
    Rule(
        component="Saarthi upstream tool gating",
        owner="services/investigation-agent",
        priority="P0",
        path_glob="services/investigation-agent/src/investigation_agent/tools.py",
        pattern=r"graph_disabled|decision_api_disabled|not set|return \{\"\s*error\"",
        rationale="Tool errors vary in shape and are hard to reason about in UI and adapters.",
        hardening_hint="Normalize tool error schema with upstream/severity/retryability hints.",
    ),
    Rule(
        component="Saarthi tabular batch store",
        owner="services/investigation-agent",
        priority="P1",
        path_glob="services/investigation-agent/src/investigation_agent/batch_store.py",
        pattern=r"disk|ttl_seconds|durable_until|storage_mode",
        rationale="Batch uploads need explicit durability contracts for multi-instance rollout.",
        hardening_hint="Disk TTL + storage_mode already shipped; keep response fields honest.",
    ),
    Rule(
        component="Investigation static UI",
        owner="services/case-api",
        priority="P1",
        path_glob="services/case-api/src/case_api/static/index.html",
        pattern=r"Minimal UI|/v1/cases/.*/graph",
        rationale="Static shell does not expose newer hardening paths and diverges from React app.",
        hardening_hint="Deprecate to smoke-only shell or align to modern APIs.",
    ),
    Rule(
        component="Case views persistence",
        owner="services/case-api",
        priority="P1",
        path_glob="services/case-api/src/case_api/main.py",
        pattern=r"CaseView|/v1/case-views",
        rationale="Saved views must stay durable across restarts and horizontal scaling.",
        hardening_hint="Postgres CaseView model is SoR; keep API semantics stable.",
    ),
    Rule(
        component="Graph benchmark run store",
        owner="services/graph-service",
        priority="P2",
        path_glob="services/graph-service/src/graph_service/main.py",
        pattern=r"_BENCHMARK_RUNS|process_memory|durability",
        rationale="Benchmark run retention is process-memory; responses must label durability.",
        hardening_hint="Keep durability: process_memory on store; optional durable backend later.",
    ),
    Rule(
        component="Ops pipelines UI depth",
        owner="frontend",
        priority="P2",
        path_glob="frontend/src/pages/OpsPipelines.tsx",
        pattern=r"ingest\.ingestStats|Total contract rejects",
        rationale="UI is useful but narrow; operators lack linked scorecard and trend context.",
        hardening_hint="Add analytics scorecard + weekly export preview/health.",
    ),
    Rule(
        component="Frontend mock mode",
        owner="frontend",
        priority="P1",
        path_glob="frontend/src/api/client.ts",
        pattern=r"VITE_USE_API_MOCKS|getMockResponse",
        rationale="Mock mode can silently mask backend regressions if enabled in non-dev pipelines.",
        hardening_hint="Add CI guard for production builds.",
    ),
    Rule(
        component="Weekly scorecard exporter",
        owner="scripts/analytics",
        priority="P2",
        path_glob="scripts/analytics/export_weekly_scorecard_json.py",
        pattern=r"stub|weekly aggregate export",
        rationale="Exporter produces base artifact but lacks integrity and publish hooks.",
        hardening_hint="Add digest/integrity fields and optional object-store output.",
    ),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _scan_file(path: Path, regex: re.Pattern[str]) -> list[int]:
    out: list[int] = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if regex.search(line):
            out.append(i)
    return out


def inventory() -> list[dict[str, object]]:
    root = _repo_root()
    rows: list[dict[str, object]] = []
    for rule in RULES:
        for file_path in root.glob(rule.path_glob):
            if not file_path.is_file():
                continue
            lines = _scan_file(file_path, re.compile(rule.pattern, flags=re.IGNORECASE))
            if not lines:
                continue
            rows.append(
                {
                    "component": rule.component,
                    "owner": rule.owner,
                    "priority": rule.priority,
                    "path": str(file_path.relative_to(root)),
                    "line_hits": lines[:20],
                    "match_count": len(lines),
                    "rationale": rule.rationale,
                    "hardening_hint": rule.hardening_hint,
                }
            )
    return sorted(rows, key=lambda r: (str(r["priority"]), str(r["owner"]), str(r["component"])))


def _markdown(rows: Iterable[dict[str, object]]) -> str:
    lines = [
        "# Lightweight Implementation Inventory",
        "",
        "Generated by `infra/scripts/ci/inventory_light_implementations.py`.",
        "",
        "| Priority | Component | Owner | Path | Evidence (line hits) | Why this matters | Hardening hint |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        evidence = ",".join(str(x) for x in row["line_hits"]) if row.get("line_hits") else "-"
        lines.append(
            "| {priority} | {component} | {owner} | `{path}` | {evidence} | {rationale} | {hardening_hint} |".format(
                **row,
                evidence=evidence,
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventory lightweight implementations for hardening."
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown")
    parser.add_argument("--write", default="", help="Write output to file path")
    args = parser.parse_args()

    rows = inventory()
    payload = json.dumps(rows, indent=2) if args.json else _markdown(rows)
    if args.write:
        out_path = (_repo_root() / args.write).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            payload + ("\n" if not payload.endswith("\n") else ""), encoding="utf-8"
        )
        print(str(out_path.relative_to(_repo_root())))
        return 0
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
