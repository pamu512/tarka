"""CLI: export labeled rows, train+gate, or serve the optional scorer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from decision_api.gnn_loop.export import export_labeled_rows, write_export_jsonl
from decision_api.gnn_loop.receipts import load_receipts
from decision_api.gnn_loop.train import train_and_gate, write_gate_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="decision_api.gnn_loop")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ex = sub.add_parser("export", help="Write labeled JSONL; skip unlabeled")
    p_ex.add_argument("--tenant-id", required=True)
    p_ex.add_argument("--out", required=True, type=Path)

    p_tr = sub.add_parser("train", help="Train offline; write gate (fail closed)")
    p_tr.add_argument("--export", required=True, type=Path)
    p_tr.add_argument("--gate-out", required=True, type=Path)

    sub.add_parser("serve", help="HTTP scorer for GRAPH_GNN_BETA_URL (gated)")

    args = parser.parse_args(argv)
    if args.cmd == "export":
        rows = export_labeled_rows(args.tenant_id, load_receipts(args.tenant_id))
        write_export_jsonl(rows, args.out)
        print(json.dumps({"rows": len(rows), "trainable": sum(1 for r in rows if r["trainable"])}))
        return 0
    if args.cmd == "train":
        rows = []
        if args.export.is_file():
            for line in args.export.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        gate = train_and_gate(rows)
        write_gate_artifact(args.gate_out, gate)
        print(json.dumps({k: gate[k] for k in ("serve_allowed", "reason", "model_auc", "heuristic_auc")}))
        return 0 if not gate.get("serve_allowed") or gate.get("serve_allowed") is True else 1
    if args.cmd == "serve":
        import uvicorn

        from decision_api.gnn_loop.serve import build_app

        uvicorn.run(build_app(), host="0.0.0.0", port=int(__import__("os").environ.get("PORT", "8091")))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
