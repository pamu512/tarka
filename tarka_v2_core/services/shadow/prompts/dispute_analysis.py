"""Assemble a single Ollama-ready prompt for Shadow **dispute** analysis (text + graph + DuckDB)."""

from __future__ import annotations

import json
from typing import Any, Final

SECTION_EXTRACTED_TEXT: Final[str] = "=== EXTRACTED TEXT ==="
SECTION_GRAPH_SNAPSHOT: Final[str] = "=== GRAPH SNAPSHOT (JSON) ==="
SECTION_DUCKDB_METRICS: Final[str] = "=== DUCKDB METRICS (JSON) ==="

_OLLAMA_ROLE_PREAMBLE: Final[str] = (
    "You are a senior payments dispute analyst assisting an on-prem Shadow agent (Ollama).\n"
    "Use ONLY the evidence in the three sections below. Do not invent transactions, graph edges, "
    "or metrics. If a section is empty, say so explicitly rather than guessing.\n"
    "Respond in clear structured prose (and JSON sub-objects only when the caller requests a "
    "machine-readable block in their follow-up).\n\n"
)


def _strip_or_empty(s: str | None) -> str:
    return (s or "").strip()


def build_dispute_ollama_prompt(
    *,
    extracted_text: str,
    graph_snapshot: dict[str, Any],
    duckdb_metrics: dict[str, Any],
) -> str:
    """
    Combine **extracted text** (e.g. PDF/email/chargeback narrative), a **graph snapshot** dict
    (neighborhood / device-IP context), and **DuckDB metrics** (spend, cluster loss, velocity, …)
    into one plain-text prompt suitable for ``/api/chat`` content to Ollama.
    """
    body = _strip_or_empty(extracted_text)
    graph_json = json.dumps(graph_snapshot, indent=2, sort_keys=True, ensure_ascii=False)
    duck_json = json.dumps(duckdb_metrics, indent=2, sort_keys=True, ensure_ascii=False)

    return (
        _OLLAMA_ROLE_PREAMBLE
        + f"{SECTION_EXTRACTED_TEXT}\n{body}\n\n"
        + f"{SECTION_GRAPH_SNAPSHOT}\n{graph_json}\n\n"
        + f"{SECTION_DUCKDB_METRICS}\n{duck_json}\n"
    )


def print_final_dispute_prompt(
    *,
    extracted_text: str,
    graph_snapshot: dict[str, Any],
    duckdb_metrics: dict[str, Any],
) -> str:
    """Build the dispute prompt, **print** it verbatim (gate / operator visibility), and return it."""
    prompt = build_dispute_ollama_prompt(
        extracted_text=extracted_text,
        graph_snapshot=graph_snapshot,
        duckdb_metrics=duckdb_metrics,
    )
    print(prompt, end="")
    return prompt


def dispute_prompt_fields_populated(
    *,
    extracted_text: str,
    graph_snapshot: dict[str, Any],
    duckdb_metrics: dict[str, Any],
) -> bool:
    """Return True when all three inputs carry usable analyst-facing data (for guards or tests)."""
    return bool(_strip_or_empty(extracted_text)) and isinstance(graph_snapshot, dict) and len(
        graph_snapshot
    ) > 0 and isinstance(duckdb_metrics, dict) and len(duckdb_metrics) > 0


def assert_dispute_prompt_data_populated(prompt: str) -> None:
    """
    Verify the assembled prompt includes all section headers and non-empty payloads.

    Raises ``AssertionError`` when a section is missing or clearly empty (gate helper).
    """
    assert SECTION_EXTRACTED_TEXT in prompt, "missing extracted text section header"
    assert SECTION_GRAPH_SNAPSHOT in prompt, "missing graph snapshot section header"
    assert SECTION_DUCKDB_METRICS in prompt, "missing duckdb metrics section header"

    after_text = prompt.split(SECTION_EXTRACTED_TEXT, 1)[1]
    text_block = after_text.split(SECTION_GRAPH_SNAPSHOT, 1)[0].strip()
    assert len(text_block) > 0, "extracted text body is empty"

    after_graph = after_text.split(SECTION_GRAPH_SNAPSHOT, 1)[1]
    graph_block = after_graph.split(SECTION_DUCKDB_METRICS, 1)[0].strip()
    assert graph_block not in ("", "{}"), "graph snapshot JSON is empty"

    duck_block = after_graph.split(SECTION_DUCKDB_METRICS, 1)[1].strip()
    assert duck_block not in ("", "{}"), "duckdb metrics JSON is empty"

    # JSON sections must round-trip (catches truncated paste errors in gates).
    json.loads(graph_block)
    json.loads(duck_block)
