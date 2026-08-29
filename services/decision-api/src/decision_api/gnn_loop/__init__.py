"""Offline GNN label loop. Not a live model claim.

Evaluate still decides via Rust packs. This package snapshots the graph
neighborhood at evaluate time, joins y_label + why, exports labeled rows,
and trains offline. Serve stays off unless holdout beats heuristic_v1.
"""

from __future__ import annotations

SCHEMA_ID = "tarka.gnn_receipt/v1"
GATE_SCHEMA_ID = "tarka.gnn_loop_gate/v1"
CHARGEBACK_CLASSES = frozenset({"FRAUD", "FRIENDLY", "SERVICE", "UNKNOWN"})
