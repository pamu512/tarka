import pytest
from investigation_agent import knowledge_store
from investigation_agent.knowledge_db import reset_connection_for_tests


@pytest.fixture(autouse=True)
def isolated_rag_db(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KNOWLEDGE_TTL_SECONDS", "86400")
    reset_connection_for_tests()
    yield
    reset_connection_for_tests()


def test_ingest_and_search():
    doc_id = knowledge_store.ingest_document(
        "t1", "a1", "Runbook", "refund abuse patterns\n\nVPN velocity"
    )
    assert doc_id
    hits = knowledge_store.search("t1", "a1", "refund VPN", limit=3)
    assert len(hits) >= 1
    assert hits[0]["doc_id"] == doc_id


def test_search_other_scope_empty():
    knowledge_store.ingest_document("t2", "a2", "x", "secret memo alpha")
    assert knowledge_store.search("t1", "a1", "secret memo") == []


def test_count_docs():
    knowledge_store.ingest_document("t3", "a3", "one", "hello")
    assert knowledge_store.count_docs("t3", "a3") >= 1
