"""Gate (Prompt 124): dispute Ollama prompt prints once and includes text + graph + DuckDB sections."""

from __future__ import annotations

import sys
from pathlib import Path

_SERVICES = Path(__file__).resolve().parents[2]
if str(_SERVICES) not in sys.path:
    sys.path.insert(0, str(_SERVICES))


def test_print_final_prompt_populates_all_data_fields(capsys: object) -> None:
    from shadow.prompts.dispute_analysis import (
        SECTION_DUCKDB_METRICS,
        SECTION_EXTRACTED_TEXT,
        SECTION_GRAPH_SNAPSHOT,
        assert_dispute_prompt_data_populated,
        print_final_dispute_prompt,
    )

    extracted = (
        "Dispute artifact excerpt: customer alleges unauthorized card use on order ORD-9001; "
        "merchant submitted signed delivery POD dated 2026-05-02."
    )
    graph = {
        "anchor_user_id": "cust_dispute_gate",
        "found": True,
        "network_device_ids": ["device_sha_gate"],
        "network_ip_addresses": ["198.51.100.77"],
        "blocked_device_touch_count": 1,
        "backend": "janusgraph",
    }
    duck = {
        "source": "duckdb",
        "cluster_loss": 425.0,
        "cluster_loss_session_count": 2,
        "total_spend": 52.5,
        "txn_count": 2,
    }

    final = print_final_dispute_prompt(
        extracted_text=extracted,
        graph_snapshot=graph,
        duckdb_metrics=duck,
    )
    printed = capsys.readouterr().out
    assert printed == final
    assert_dispute_prompt_data_populated(final)

    assert SECTION_EXTRACTED_TEXT in final
    assert SECTION_GRAPH_SNAPSHOT in final
    assert SECTION_DUCKDB_METRICS in final
    assert "ORD-9001" in final
    assert "device_sha_gate" in final
    assert "cluster_loss" in final and "425" in final
    assert "total_spend" in final
