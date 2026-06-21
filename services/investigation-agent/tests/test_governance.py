"""Regional AI governance profiles."""

from investigation_agent.governance import (
    governance_profile_label,
    governance_profile_references,
    normalize_governance_profile,
    regional_system_prompt_append,
)


def test_normalize_aliases():
    assert normalize_governance_profile("US") == "us"
    assert normalize_governance_profile("eu") == "eu_uk"
    assert normalize_governance_profile("UK") == "eu_uk"
    assert normalize_governance_profile("global") == "global"
    assert normalize_governance_profile("unknown-land") == "global"


def test_prompt_blocks_non_empty():
    for raw in ("us", "eu_uk", "global"):
        p = normalize_governance_profile(raw)
        block = regional_system_prompt_append(p)
        assert "REGIONAL GOVERNANCE" in block
        assert len(block) > 200


def test_references_lists():
    assert any("NIST" in r for r in governance_profile_references("us"))
    assert any("GDPR" in r or "AI Act" in r for r in governance_profile_references("eu_uk"))
    assert any("ISO" in r for r in governance_profile_references("global"))


def test_labels():
    assert "United States" in governance_profile_label("us")
    assert "EU" in governance_profile_label("eu_uk")
