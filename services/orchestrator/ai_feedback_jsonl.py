"""Append structured AI analyst feedback to a local JSONL file (RAG / fine-tuning export)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_append_lock = threading.Lock()


def resolve_ai_feedback_jsonl_path(override: str | os.PathLike[str] | None) -> Path:
    """Target path for ``POST /v1/ai/feedback`` rows.

    Resolution order:
    1. Explicit ``override`` (tests / dependency injection).
    2. :envvar:`ORCHESTRATOR_AI_FEEDBACK_JSONL` — full file path.
    3. ``{ORCHESTRATOR_DATA_DIR or cwd}/data/ai_rejection_feedback.jsonl``
    """
    if override is not None:
        p = Path(override).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    env = (os.environ.get("ORCHESTRATOR_AI_FEEDBACK_JSONL") or "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    root = Path((os.environ.get("ORCHESTRATOR_DATA_DIR") or "").strip() or Path.cwd())
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return (data_dir / "ai_rejection_feedback.jsonl").resolve()


def append_feedback_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON object as a single line (UTF-8), process-wide locked."""
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _append_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
