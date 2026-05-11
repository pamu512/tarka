"""Prompt builders for Shadow-side workflows (outside the HTTP ``shadow_agent`` package)."""

from .dispute_analysis import (
    SECTION_DUCKDB_METRICS,
    SECTION_EXTRACTED_TEXT,
    SECTION_GRAPH_SNAPSHOT,
    assert_dispute_prompt_data_populated,
    build_dispute_ollama_prompt,
    dispute_prompt_fields_populated,
    print_final_dispute_prompt,
)

__all__ = [
    "SECTION_DUCKDB_METRICS",
    "SECTION_EXTRACTED_TEXT",
    "SECTION_GRAPH_SNAPSHOT",
    "assert_dispute_prompt_data_populated",
    "build_dispute_ollama_prompt",
    "dispute_prompt_fields_populated",
    "print_final_dispute_prompt",
]
