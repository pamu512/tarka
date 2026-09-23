"""Retrieval smoke on committed OKF fixtures.

Cites required OR explicit abstain. Zero cites without abstain is a fail —
empty retrieval is not a soft success.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from investigation_agent.okf_registry import OkfRegistry
from investigation_agent.okf_retrieval import KnowledgeRetrievalResult, retrieve_knowledge

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "okf"


def assert_retrieval_honest(result: KnowledgeRetrievalResult) -> None:
    cites = [item.concept_id for item in result.results if item.concept_id]
    if cites:
        return
    if result.abstain:
        return
    pytest.fail(
        "empty retrieval without abstain is soft success: "
        f"results={len(result.results)} abstain={result.abstain} mode={result.retrieval_mode}"
    )


@pytest.fixture
def fixture_registry(tmp_path: Path) -> OkfRegistry:
    shared = tmp_path / "shared"
    tenants = tmp_path / "tenants"
    shutil.copytree(_FIXTURES / "shared", shared)
    shutil.copytree(_FIXTURES / "tenants", tenants)
    registry = OkfRegistry(shared_root=shared, tenant_root=tenants)
    activated = registry.reload()
    assert activated.activated is True, activated.issues
    return registry


def test_fixture_query_requires_cites_or_abstain(fixture_registry: OkfRegistry) -> None:
    result = retrieve_knowledge(
        registry=fixture_registry,
        tenant_id="t1",
        analyst_id="sop-smoke",
        query="high-amount",
        limit=5,
        rag_search=lambda **_: {"hits": [], "retrieval_mode": "keyword"},
    )
    assert_retrieval_honest(result)
    cites = [item.concept_id for item in result.results if item.concept_id]
    assert cites, "known fixture query must return OKF cites"
    assert "playbooks/high-amount-review" in cites
    assert result.abstain is False


def test_unknown_query_must_abstain_not_soft_empty(fixture_registry: OkfRegistry) -> None:
    result = retrieve_knowledge(
        registry=fixture_registry,
        tenant_id="t1",
        analyst_id="sop-smoke",
        query="no-such-okf-concept-zzzz",
        limit=5,
        rag_search=lambda **_: {"hits": [], "retrieval_mode": "keyword"},
    )
    cites = [item.concept_id for item in result.results if item.concept_id]
    assert cites == []
    assert result.abstain is True
    assert_retrieval_honest(result)


def test_zero_cites_without_abstain_is_not_ok() -> None:
    dishonest = KnowledgeRetrievalResult(
        results=(),
        retrieval_mode="keyword",
        conflicts=(),
        abstain=False,
        bundle_revision="0" * 64,
    )
    with pytest.raises(pytest.fail.Exception, match="soft success"):
        assert_retrieval_honest(dishonest)
