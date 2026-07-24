"""End-to-end OKF gates for activation, retrieval, fallback, and packaging."""

from __future__ import annotations

import asyncio
from typing import Any
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from investigation_agent import knowledge_db
import investigation_agent.main as main_mod
from investigation_agent.citation_schema import build_standard_citations
from investigation_agent.knowledge_db import ingest_document_sync, reset_connection_for_tests
from investigation_agent.main import app
from investigation_agent.okf_registry import OkfRegistry
from investigation_agent.okf_retrieval import retrieve_knowledge_async
from investigation_agent.tools import tool_search_knowledge

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_index(root: Path, heading: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.md").write_text(
        f'---\nokf_version: "0.1"\n---\n# {heading}\n',
        encoding="utf-8",
    )


def _approved_frontmatter(
    *,
    concept_type: str,
    title: str,
    tenant_scope: str,
    source_uri: str,
    source_hash_char: str,
    tags: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
) -> str:
    lines = [
        "---",
        f"type: {concept_type}",
        f"title: {title}",
    ]
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {tag}" for tag in tags)
    lines.extend(
        [
            f"tenant_scope: {tenant_scope}",
            f"source_uri: {source_uri}",
            f"source_content_hash: {source_hash_char * 64}",
            "approval_status: approved",
            "approved_revision: approved-rev-1",
            "sensitivity: internal",
        ]
    )
    if evidence_ids:
        lines.append("evidence_ids:")
        lines.extend(f"  - {evidence_id}" for evidence_id in evidence_ids)
    return "\n".join([*lines, "---", ""])


def _write_concept(
    root: Path,
    rel_path: str,
    *,
    concept_type: str,
    title: str,
    tenant_scope: str,
    source_uri: str,
    source_hash_char: str,
    tags: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
    body: str,
) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _approved_frontmatter(
            concept_type=concept_type,
            title=title,
            tenant_scope=tenant_scope,
            source_uri=source_uri,
            source_hash_char=source_hash_char,
            tags=tags,
            evidence_ids=evidence_ids,
        )
        + body.rstrip()
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def isolated_knowledge_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path / "rag"))
    monkeypatch.setenv("KNOWLEDGE_TTL_SECONDS", "86400")
    main_mod._valid_api_keys = None
    reset_connection_for_tests()
    yield
    main_mod._valid_api_keys = None
    reset_connection_for_tests()


def _build_bundle_tree(shared_root: Path, tenant_root: Path) -> None:
    _write_index(shared_root, "Shared approved OKF")
    _write_concept(
        shared_root,
        "rules/high-amount.md",
        concept_type="Fraud Rule",
        title="High Amount Rule",
        tenant_scope="shared",
        source_uri="rules/default.json#high-amount",
        source_hash_char="a",
        tags=("high-amount",),
        body="Default shared high amount threshold guidance.",
    )
    _write_concept(
        shared_root,
        "references/kyc-checklist.md",
        concept_type="Reference",
        title="KYC Checklist",
        tenant_scope="shared",
        source_uri="references/kyc-checklist.json",
        source_hash_char="b",
        body="Confirm profile, address, and expected account activity.",
    )

    t1 = tenant_root / "t1"
    _write_index(t1, "Tenant t1 approved OKF")
    _write_concept(
        t1,
        "rules/high-amount.md",
        concept_type="Fraud Rule",
        title="High Amount Rule",
        tenant_scope="t1",
        source_uri="rules/t1/high-amount.json",
        source_hash_char="c",
        tags=("high-amount",),
        evidence_ids=("ev-rule",),
        body=(
            "Tenant t1 high amount rule.\n\n"
            "Run [High Amount Review Playbook](../playbooks/high-amount-review.md) "
            "and verify [KYC Checklist](/shared/references/kyc-checklist.md)."
        ),
    )
    _write_concept(
        t1,
        "playbooks/high-amount-review.md",
        concept_type="Investigation Playbook",
        title="High Amount Review Playbook",
        tenant_scope="t1",
        source_uri="playbooks/t1/high-amount-review.json",
        source_hash_char="d",
        tags=("playbook",),
        evidence_ids=("ev-playbook",),
        body="Review customer profile, transaction velocity, and chargeback history.",
    )

    t2 = tenant_root / "t2"
    _write_index(t2, "Tenant t2 approved OKF")
    _write_concept(
        t2,
        "playbooks/t2-secret.md",
        concept_type="Investigation Playbook",
        title="T2 Secret Playbook",
        tenant_scope="t2",
        source_uri="playbooks/t2/secret.json",
        source_hash_char="e",
        tags=("t2-secret",),
        body="Tenant t2 only handling instructions.",
    )


def _configure_okf_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    shared_root: Path,
    tenant_root: Path,
    embeddings: bool,
) -> None:
    monkeypatch.setattr(main_mod.settings, "okf_enabled", True)
    monkeypatch.setattr(main_mod.settings, "okf_shared_root", str(shared_root))
    monkeypatch.setattr(main_mod.settings, "okf_tenant_root", str(tenant_root))
    monkeypatch.setattr(main_mod.settings, "copilot_knowledge_embeddings", embeddings)
    monkeypatch.setattr(main_mod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(main_mod.settings, "copilot_embedding_api_key", "")
    monkeypatch.setattr(
        main_mod.settings,
        "copilot_embedding_base_url",
        "http://embeddings.local/v1",
    )
    monkeypatch.setattr(main_mod.settings, "copilot_embedding_model", "test-embedding")
    monkeypatch.setattr(main_mod.settings, "allowed_analysts", "*")
    main_mod._valid_api_keys = None


async def _semantic_embeddings(*_: Any, texts: list[str], **__: Any) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        lowered = text.casefold()
        if "fresh reload marker" in lowered:
            vectors.append([0.0, 1.0, 0.0])
        elif "account activity" in lowered or "confirm profile" in lowered:
            vectors.append([1.0, 0.0, 0.0])
        else:
            vectors.append([0.0, 0.0, 1.0])
    return vectors


def _tool_search(client: TestClient, *, tenant_id: str, query: str, limit: int = 5) -> dict:
    return client.portal.call(
        tool_search_knowledge,
        client.app.state.http,
        tenant_id,
        "analyst-1",
        query,
        limit,
        client.app.state.okf_registry,
    )


def test_startup_indexes_bundles_before_ready_and_tool_uses_hybrid_and_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
        embeddings=True,
    )
    monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", _semantic_embeddings)
    real_preparer = main_mod.knowledge_store.prepare_okf_index_rows_async
    indexed_bundles: list[tuple[str, str | None]] = []

    async def spy_preparer(
        http: Any, bundles: tuple[Any, ...], **kwargs: Any
    ) -> tuple[tuple[Any, ...], int]:
        indexed_bundles.extend((bundle.scope, bundle.tenant_id) for bundle in bundles)
        return await real_preparer(http, bundles, **kwargs)

    monkeypatch.setattr(main_mod.knowledge_store, "prepare_okf_index_rows_async", spy_preparer)

    with TestClient(app) as client:
        ready = client.get("/v1/ready")
        assert ready.status_code == 200
        assert {scope for scope, _ in indexed_bundles} == {"shared", "tenant"}
        assert ("tenant", "t1") in indexed_bundles
        assert ("tenant", "t2") in indexed_bundles

        hybrid = _tool_search(client, tenant_id="t1", query="account activity", limit=3)
        assert hybrid["retrieval_mode"] == "hybrid"
        assert hybrid["hits"][0]["concept_id"] == "references/kyc-checklist"
        assert hybrid["hits"][0]["authority_label"] == "shared_okf"

        ingest_document_sync(
            "t1",
            "analyst-1",
            "Residual high amount memo",
            "Residual chargeback memo for high amount rule escalation and manual review.",
        )

        async def fail_embeddings(*_: Any, **__: Any) -> list[list[float]]:
            raise RuntimeError("embedding service unavailable")

        monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", fail_embeddings)

        fallback = _tool_search(client, tenant_id="t1", query="High Amount Rule", limit=4)
        assert fallback["retrieval_mode"] == "exact+expand+keyword_fallback"
        assert [hit["concept_id"] for hit in fallback["hits"]] == [
            "rules/high-amount",
            "playbooks/high-amount-review",
            "references/kyc-checklist",
            None,
        ]
        assert [hit["authority_label"] for hit in fallback["hits"]] == [
            "tenant_okf",
            "tenant_okf",
            "shared_okf",
            "memo_rag",
        ]
        assert fallback["hits"][1]["retrieval_path"] == [
            "rules/high-amount",
            "playbooks/high-amount-review",
        ]

        allowed_concepts = {hit["concept_id"] for hit in fallback["hits"] if hit["concept_id"]}
        allowed_evidence = {
            evidence_id for hit in fallback["hits"] for evidence_id in hit["evidence_ids"]
        }
        claim_concepts = [
            hit["concept_id"] for hit in fallback["hits"] if hit["authority"] == "tenant_okf"
        ]
        claim_evidence = [
            evidence_id
            for hit in fallback["hits"]
            if hit["authority"] == "tenant_okf"
            for evidence_id in hit["evidence_ids"]
        ]
        citations, summary = build_standard_citations(
            claims=[
                {
                    "text": "Use the high amount rule and linked playbook.",
                    "source": "tool",
                    "concept_ids": claim_concepts,
                    "evidence_ids": claim_evidence,
                }
            ],
            deterministic_support=[{"claim_index": 0, "supported": True}],
            allowed_concept_ids=allowed_concepts,
            allowed_evidence_ids=allowed_evidence,
        )
        resolved = {(item["artifact"], item["id"]) for item in citations[0]["resolves_to"]}
        assert summary.supported_count == 1
        assert ("okf_concept", "rules/high-amount") in resolved
        assert ("okf_concept", "playbooks/high-amount-review") in resolved
        assert ("evidence", "ev-rule") in resolved
        assert ("evidence", "ev-playbook") in resolved

        t2_result = _tool_search(client, tenant_id="t1", query="T2 Secret Playbook", limit=5)
        assert "playbooks/t2-secret" not in {hit["concept_id"] for hit in t2_result["hits"]}


def test_admin_reload_refreshes_index_and_failed_reload_keeps_prior_searchable_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
        embeddings=True,
    )
    monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", _semantic_embeddings)
    monkeypatch.setenv("API_KEYS", "admin-key")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"admin-key":["t1"]}')
    monkeypatch.setenv("OKF_ADMIN_API_KEYS", "admin-key")
    main_mod._valid_api_keys = None
    real_preparer = main_mod.knowledge_store.prepare_okf_index_rows_async
    indexed_after_reload: list[tuple[str, str | None]] = []

    async def spy_preparer(
        http: Any, bundles: tuple[Any, ...], **kwargs: Any
    ) -> tuple[tuple[Any, ...], int]:
        indexed_after_reload.extend((bundle.scope, bundle.tenant_id) for bundle in bundles)
        return await real_preparer(http, bundles, **kwargs)

    monkeypatch.setattr(main_mod.knowledge_store, "prepare_okf_index_rows_async", spy_preparer)

    with TestClient(app) as client:
        indexed_after_reload.clear()
        _write_concept(
            tenant_root / "t1",
            "playbooks/fresh-reload.md",
            concept_type="Investigation Playbook",
            title="Fresh Reload Playbook",
            tenant_scope="t1",
            source_uri="playbooks/t1/fresh-reload.json",
            source_hash_char="f",
            evidence_ids=("ev-reload",),
            body="Fresh reload marker guidance for newly approved overlays.",
        )

        reload_response = client.post(
            "/v1/admin/okf/reload",
            headers={"x-api-key": "admin-key"},
        )
        assert reload_response.status_code == 200
        assert reload_response.json()["activated"] is True
        assert ("shared", None) in indexed_after_reload
        assert ("tenant", "t1") in indexed_after_reload
        refreshed = _tool_search(
            client,
            tenant_id="t1",
            query="fresh reload marker",
            limit=3,
        )
        assert refreshed["retrieval_mode"] == "hybrid"
        assert refreshed["hits"][0]["concept_id"] == "playbooks/fresh-reload"

        prior_revision = client.app.state.okf_reload_result.revision
        indexed_after_reload.clear()
        (shared_root / "rules" / "high-amount.md").write_text(
            "invalid\n",
            encoding="utf-8",
        )
        failed = client.post(
            "/v1/admin/okf/reload",
            headers={"x-api-key": "admin-key"},
        )
        assert failed.status_code == 200
        assert failed.json()["activated"] is False
        assert client.app.state.okf_reload_result.revision == prior_revision
        assert indexed_after_reload == []
        ready = client.get("/v1/ready", headers={"x-api-key": "admin-key"})
        assert ready.status_code == 200
        still_searchable = _tool_search(
            client,
            tenant_id="t1",
            query="fresh reload marker",
            limit=3,
        )
        assert still_searchable["hits"][0]["concept_id"] == "playbooks/fresh-reload"


def test_admin_reload_purges_removed_okf_concepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
        embeddings=True,
    )
    monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", _semantic_embeddings)
    monkeypatch.setenv("API_KEYS", "admin-key")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"admin-key":["t1"]}')
    monkeypatch.setenv("OKF_ADMIN_API_KEYS", "admin-key")
    main_mod._valid_api_keys = None

    with TestClient(app) as client:
        concept_path = tenant_root / "t1" / "playbooks" / "fresh-reload.md"
        _write_concept(
            tenant_root / "t1",
            "playbooks/fresh-reload.md",
            concept_type="Investigation Playbook",
            title="Fresh Reload Playbook",
            tenant_scope="t1",
            source_uri="playbooks/t1/fresh-reload.json",
            source_hash_char="f",
            evidence_ids=("ev-reload",),
            body="Fresh reload marker guidance for newly approved overlays.",
        )
        assert (
            client.post("/v1/admin/okf/reload", headers={"x-api-key": "admin-key"}).json()[
                "activated"
            ]
            is True
        )
        assert (
            _tool_search(client, tenant_id="t1", query="fresh reload marker")["hits"][0][
                "concept_id"
            ]
            == "playbooks/fresh-reload"
        )

        concept_path.unlink()
        purged = client.post("/v1/admin/okf/reload", headers={"x-api-key": "admin-key"})
        assert purged.status_code == 200
        assert purged.json()["activated"] is True
        after_purge = _tool_search(client, tenant_id="t1", query="fresh reload marker")
        assert "playbooks/fresh-reload" not in {hit["concept_id"] for hit in after_purge["hits"]}
        row = (
            knowledge_db._get_conn()
            .execute(
                """
            SELECT COUNT(*) FROM knowledge_chunks
            WHERE knowledge_kind = 'okf' AND concept_id = 'playbooks/fresh-reload'
            """
            )
            .fetchone()
        )
        assert row[0] == 0


def test_mid_index_failure_rolls_back_registry_and_search_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
        embeddings=True,
    )
    monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", _semantic_embeddings)
    monkeypatch.setenv("API_KEYS", "admin-key")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"admin-key":["t1"]}')
    monkeypatch.setenv("OKF_ADMIN_API_KEYS", "admin-key")
    main_mod._valid_api_keys = None

    with TestClient(app) as client:
        prior_revision = client.app.state.okf_reload_result.revision
        prior_hit = _tool_search(client, tenant_id="t1", query="account activity")
        assert prior_hit["hits"][0]["concept_id"] == "references/kyc-checklist"

        _write_concept(
            tenant_root / "t1",
            "playbooks/mid-failure.md",
            concept_type="Investigation Playbook",
            title="Mid Failure Playbook",
            tenant_scope="t1",
            source_uri="playbooks/t1/mid-failure.json",
            source_hash_char="9",
            evidence_ids=("ev-mid-failure",),
            body="Mid failure marker guidance for injected rollback.",
        )
        original_insert = getattr(knowledge_db, "_insert_okf_index_row", None)
        inserted = 0

        def fail_after_first_insert(*args: Any, **kwargs: Any) -> None:
            nonlocal inserted
            inserted += 1
            if original_insert is not None:
                original_insert(*args, **kwargs)
            if inserted == 1:
                raise RuntimeError("injected mid-index failure")

        monkeypatch.setattr(
            knowledge_db,
            "_insert_okf_index_row",
            fail_after_first_insert,
            raising=False,
        )
        failed = client.post("/v1/admin/okf/reload", headers={"x-api-key": "admin-key"})
        assert failed.status_code == 503
        assert failed.json()["detail"] == "okf_index_failed"
        assert client.app.state.okf_reload_result.revision == prior_revision
        ready = client.get("/v1/ready", headers={"x-api-key": "admin-key"})
        assert ready.status_code == 200
        still_prior = _tool_search(client, tenant_id="t1", query="account activity")
        assert still_prior["hits"][0]["concept_id"] == "references/kyc-checklist"
        not_visible = _tool_search(client, tenant_id="t1", query="mid failure marker")
        assert "playbooks/mid-failure" not in {hit["concept_id"] for hit in not_visible["hits"]}


@pytest.mark.asyncio
async def test_async_retrieval_holds_generation_gate_until_rag_completes(
    tmp_path: Path,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    assert registry.reload().activated is True

    gate = asyncio.Lock()
    rag_started = asyncio.Event()
    allow_rag_finish = asyncio.Event()
    reload_entered = asyncio.Event()

    async def rag_search(**_kwargs: Any) -> dict[str, Any]:
        rag_started.set()
        await allow_rag_finish.wait()
        return {
            "hits": [
                {
                    "title": "Analyst memo",
                    "snippet": "Memo filler for high amount review.",
                    "score": 0.25,
                    "knowledge_kind": "memo",
                    "authority": 10,
                }
            ],
            "retrieval_mode": "keyword",
        }

    retrieval_task = asyncio.create_task(
        retrieve_knowledge_async(
            registry=registry,
            tenant_id="t1",
            analyst_id="analyst-1",
            query="High Amount Rule",
            limit=4,
            rag_search=rag_search,
            generation_gate=gate,
        )
    )
    await rag_started.wait()

    async def reload_attempt() -> None:
        async with gate:
            reload_entered.set()

    reload_task = asyncio.create_task(reload_attempt())
    await asyncio.sleep(0)
    assert reload_entered.is_set() is False

    allow_rag_finish.set()
    result = await retrieval_task
    await reload_task

    assert reload_entered.is_set() is True
    assert result.bundle_revision == registry.snapshot_revision("t1")
    returned = {
        item.concept_id: item.content_hash for item in result.results if item.concept_id is not None
    }
    active = {
        hit.concept.concept_id: hit.concept.content_hash
        for hit in registry.expand(
            "t1",
            ("rules/high-amount",),
            max_depth=2,
            max_concepts=4,
        )
    }
    assert returned.items() <= active.items()


@pytest.mark.asyncio
async def test_concurrent_reloads_serialize_candidate_preparation_through_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
        embeddings=False,
    )
    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    first_entered = asyncio.Event()
    first_can_finish = asyncio.Event()
    second_prepared = asyncio.Event()
    gate = asyncio.Lock()

    async def reload_once(label: str) -> str:
        async with gate:
            candidate = registry.prepare_reload()
            assert not candidate.issues
            if label == "first":
                first_entered.set()
                await first_can_finish.wait()
            else:
                second_prepared.set()
            rows, _indexed = await main_mod.knowledge_store.prepare_okf_index_rows_async(
                None,
                candidate.bundles,
                use_embeddings=False,
                api_key="",
                base_url="",
                embed_model="",
            )
            main_mod.knowledge_store.replace_okf_index_rows_sync(rows)
            result = registry.activate(candidate)
            return result.revision

    first_task = asyncio.create_task(reload_once("first"))
    await first_entered.wait()
    _write_concept(
        tenant_root / "t1",
        "playbooks/newer-reload.md",
        concept_type="Investigation Playbook",
        title="Newer Reload Playbook",
        tenant_scope="t1",
        source_uri="playbooks/t1/newer-reload.json",
        source_hash_char="d",
        evidence_ids=("ev-newer",),
        body="Newer reload marker.",
    )
    second_task = asyncio.create_task(reload_once("second"))
    await asyncio.sleep(0)
    assert second_prepared.is_set() is False

    first_can_finish.set()
    first_revision = await first_task
    second_revision = await second_task

    assert first_revision != second_revision
    assert registry.resolve("t1", "Newer Reload Playbook")[0].concept.concept_id == (
        "playbooks/newer-reload"
    )


def test_deployment_config_ships_only_shared_bundle_and_mounts_tenants() -> None:
    dockerfile = (_REPO_ROOT / "services" / "investigation-agent" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    env_reference = (
        _REPO_ROOT / "services" / "investigation-agent" / ".env.reference.example"
    ).read_text(encoding="utf-8")

    assert "COPY knowledge/shared /app/knowledge/shared" in dockerfile
    assert "OKF_SHARED_ROOT=/app/knowledge/shared" in dockerfile
    assert "OKF_TENANT_ROOT=/var/lib/tarka/knowledge/tenants" in dockerfile
    assert "COPY knowledge/tenants" not in dockerfile
    assert "OKF_ENABLED=true" in env_reference
    assert "OKF_SHARED_ROOT=/app/knowledge/shared" in env_reference
    assert "OKF_TENANT_ROOT=/var/lib/tarka/knowledge/tenants" in env_reference
    assert "OKF_MAX_LINK_DEPTH=2" in env_reference
    assert "OKF_MAX_CONCEPTS=24" in env_reference
    assert "OKF_ADMIN_API_KEYS=" in env_reference

    compose = yaml.safe_load(
        (_REPO_ROOT / "infra" / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    agent = compose["services"]["investigation-agent"]
    assert (
        "${OKF_TENANT_OVERLAYS_PATH:-../../knowledge/tenants}:/var/lib/tarka/knowledge/tenants:ro"
    ) in agent["volumes"]
    assert agent["environment"]["OKF_TENANT_ROOT"] == "/var/lib/tarka/knowledge/tenants"
    assert "OKF_ADMIN_API_KEYS" in agent["environment"]
    marker = (_REPO_ROOT / "knowledge" / "tenants" / "README.md").read_text(encoding="utf-8")
    assert "intentionally empty" in marker

    for chart_name in ("fraud-stack", "tarka", "fraud-stack-lite"):
        chart_root = _REPO_ROOT / "infra" / "deploy" / "helm" / chart_name
        helm_values = yaml.safe_load((chart_root / "values.yaml").read_text(encoding="utf-8"))
        overlay_values = helm_values["investigationAgent"]["okfTenantOverlays"]
        assert overlay_values == {
            "enabled": False,
            "existingClaim": "",
            "mountPath": "/var/lib/tarka/knowledge/tenants",
            "readOnly": True,
        }
        helm_template = (chart_root / "templates" / "investigation-agent.yaml").read_text(
            encoding="utf-8"
        )
        assert "OKF tenant overlays require investigationAgent.okfTenantOverlays.existingClaim" in (
            helm_template
        )
        assert "OKF_TENANT_ROOT" in helm_template
        assert "volumeMounts:" in helm_template
        assert "persistentVolumeClaim:" in helm_template
        assert "existingClaim" in helm_template

    ci_workflow = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "npm audit --audit-level=low" in ci_workflow
    for chart_name in ("fraud-stack", "tarka", "fraud-stack-lite"):
        assert "infra/deploy/helm/${chart}" in ci_workflow
        assert chart_name in ci_workflow

    docs = (_REPO_ROOT / "docs" / "docs" / "services" / "investigation-agent.md").read_text(
        encoding="utf-8"
    )
    assert "OKF_ADMIN_API_KEYS" in docs
    assert "API_KEYS" in docs
    assert "API_KEY_TENANT_MAP" in docs
    assert "Admin reload is process-local" in docs
    assert "rolling restart" in docs
