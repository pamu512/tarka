from __future__ import annotations
import re
from typing import Any

"""Parse optional structured section headings from assistant prose (best-effort)."""
# Markdown-style or ALL CAPS section headers the model is instructed to use
_SECTION_PATTERNS = [
    ("facts_from_tools", re.compile(r"(?:^|\n)#+\s*FACTS?\s*FROM\s*TOOLS?\s*\n", re.IGNORECASE)),
    ("inferences", re.compile(r"(?:^|\n)#+\s*INFERENCES?\s*\n", re.IGNORECASE)),
    ("unknowns", re.compile(r"(?:^|\n)#+\s*UNKNOWNS?\s*\n", re.IGNORECASE)),
    ("next_steps", re.compile(r"(?:^|\n)#+\s*NEXT\s*STEPS?\s*\n", re.IGNORECASE)),
]


def parse_structured_sections(prose: str) -> dict[str, Any]:
    """
    Split prose on section headers. Unmatched prefix goes to preamble.
    Returns { preamble?, facts_from_tools?, inferences?, unknowns?, next_steps?, sections_found: string[] }.
    """
    if not (prose or "").strip():
        return {"sections_found": []}

    text = prose
    positions: list[tuple[str, int]] = []
    for key, pat in _SECTION_PATTERNS:
        for m in pat.finditer(text):
            positions.append((key, m.start()))

    if not positions:
        return {"preamble": text.strip(), "sections_found": []}

    positions.sort(key=lambda x: x[1])
    # dedupe by first occurrence per key
    seen: set[str] = set()
    ordered: list[tuple[str, int]] = []
    for k, pos in positions:
        if k in seen:
            continue
        seen.add(k)
        ordered.append((k, pos))

    out: dict[str, Any] = {"sections_found": [k for k, _ in ordered]}
    first_start = ordered[0][1]
    if first_start > 0:
        pre = text[:first_start].strip()
        if pre:
            out["preamble"] = pre

    for i, (key, start) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(text)
        block = text[start:end]
        # strip header line itself
        lines = block.split("\n")
        if lines:
            lines = lines[1:]  # drop # HEADER line
        content = "\n".join(lines).strip()
        if content:
            out[key] = content

    return out


def structured_sections_prompt_block() -> str:
    return (
        "ANSWER STRUCTURE (required for every assistant turn, before the claims trailer):\n"
        "Use exactly these Markdown headings in order (each followed by bullets or short paragraphs):\n"
        "## FACTS FROM TOOLS\n"
        "— Only statements directly supported by tool JSON this turn. Name the tool when helpful.\n"
        "## INFERENCES\n"
        "— Hypotheses or interpretations; label uncertainty.\n"
        "## UNKNOWNS\n"
        "— What was not retrieved, tool errors, or missing data.\n"
        "## NEXT STEPS\n"
        "— Concrete follow-ups (which tool, which id).\n"
        'If a section is empty, write "None" under the heading.\n'
        'When any tool returned {"error":...}, you MUST mention that failure under UNKNOWNS or FACTS.\n\n'
    )
