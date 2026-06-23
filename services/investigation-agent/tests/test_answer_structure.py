from pathlib import Path

from investigation_agent.answer_structure import parse_structured_sections

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_parse_structured_sections_finds_headings():
    prose = """## FACTS FROM TOOLS
- a from get_case

## INFERENCES
- maybe x

## UNKNOWNS
- None

## NEXT STEPS
- get_decision_audit
"""
    out = parse_structured_sections(prose)
    assert "facts_from_tools" in out
    assert "from get_case" in out["facts_from_tools"]
    assert "inferences" in out
    assert "next_steps" in out
    assert out["sections_found"]


def test_parse_empty():
    assert parse_structured_sections("")["sections_found"] == []


def test_golden_fixture_file():
    prose = (_FIXTURES / "golden_structured_prose.md").read_text(encoding="utf-8")
    out = parse_structured_sections(prose)
    assert "facts_from_tools" in out and "c1" in out["facts_from_tools"]
    assert len(out["sections_found"]) >= 3
