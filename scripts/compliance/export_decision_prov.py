#!/usr/bin/env python3
"""Export decision context graph rows as W3C PROV-O JSON-LD (compliance pack)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export decisions as PROV-O JSON-LD")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--output", default="-")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "graph-service" / "src"))
    from graph_service.decision_context_store import search_decisions

    rows = search_decisions(tenant_id=args.tenant, limit=args.limit)
    graph: list[dict] = []
    for row in rows:
        did = row["external_id"]
        graph.append(
            {
                "@id": f"prov:decision/{did}",
                "@type": "prov:Activity",
                "prov:startedAtTime": row.get("created_at"),
                "tarka:kind": row.get("kind"),
                "tarka:category": row.get("category"),
                "tarka:scenario": row.get("scenario"),
                "tarka:outcome": row.get("outcome"),
                "tarka:reasoning": row.get("reasoning"),
            }
        )
        for rid in row.get("rule_ids") or []:
            graph.append(
                {
                    "@id": f"prov:rule/{rid}",
                    "@type": "prov:Entity",
                }
            )
            graph.append(
                {
                    "@type": "prov:WasAssociatedWith",
                    "prov:activity": {"@id": f"prov:decision/{did}"},
                    "prov:agent": {"@id": f"prov:rule/{rid}"},
                }
            )
        if row.get("invalidated_at"):
            graph.append(
                {
                    "@type": "prov:WasInvalidatedBy",
                    "prov:entity": {"@id": f"prov:decision/{did}"},
                    "prov:activity": {
                        "@id": f"prov:invalidation/{did}",
                        "@type": "prov:Activity",
                        "tarka:reason": row.get("invalidation_reason"),
                    },
                }
            )

    doc = {
        "@context": {
            "prov": "http://www.w3.org/ns/prov#",
            "tarka": "https://tarka.dev/ns/decision#",
        },
        "@graph": graph,
    }
    text = json.dumps(doc, indent=2, default=str)
    if args.output == "-":
        print(text)
    else:
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
