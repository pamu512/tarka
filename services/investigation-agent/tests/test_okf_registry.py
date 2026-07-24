"""OKF bundle registry: tenant isolation, atomic reload, bounded graph traversal."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from investigation_agent.okf_registry import OkfRegistry


@pytest.fixture
def okf_fixtures_root() -> Path:
    return Path(__file__).parent / "fixtures" / "okf"


@pytest.fixture
def shared_root(tmp_path: Path, okf_fixtures_root: Path) -> Path:
    dest = tmp_path / "shared"
    shutil.copytree(okf_fixtures_root / "shared", dest)
    return dest


@pytest.fixture
def tenant_root(tmp_path: Path, okf_fixtures_root: Path) -> Path:
    dest = tmp_path / "tenants"
    shutil.copytree(okf_fixtures_root / "tenants", dest)
    return dest


@pytest.fixture
def registry(shared_root: Path, tenant_root: Path) -> OkfRegistry:
    return OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)


def _valid_frontmatter(
    *,
    concept_type: str,
    tenant_scope: str,
    title: str,
    source_hash_char: str = "c",
) -> str:
    return (
        "---\n"
        f"type: {concept_type}\n"
        f"title: {title}\n"
        f"tenant_scope: {tenant_scope}\n"
        f"source_uri: docs/{title}\n"
        f"source_content_hash: {source_hash_char * 64}\n"
        "approval_status: approved\n"
        "approved_revision: x\n"
        "sensitivity: internal\n"
        "---\n"
    )


def test_reload_activates_valid_fixtures(registry: OkfRegistry) -> None:
    result = registry.reload()
    assert result.activated is True
    assert result.issues == ()
    assert len(result.revision) == 64


def test_resolve_shared_concept_by_title(registry: OkfRegistry) -> None:
    registry.reload()
    hits = registry.resolve("t1", "High Amount Rule")
    assert len(hits) >= 1
    ids = {hit.concept.concept_id for hit in hits}
    assert "rules/high-amount" in ids
    assert hits[0].authority == "shared"


def test_resolve_tenant_overlay_by_tag(registry: OkfRegistry) -> None:
    registry.reload()
    hits = registry.resolve("t1", "high-amount")
    ids = {hit.concept.concept_id for hit in hits}
    assert "playbooks/high-amount-review" in ids
    tenant_hits = [h for h in hits if h.concept.concept_id == "playbooks/high-amount-review"]
    assert tenant_hits[0].authority == "tenant"


def test_resolve_rejects_partial_title_and_tag(registry: OkfRegistry) -> None:
    registry.reload()
    assert registry.resolve("t1", "High Amount") == []
    assert registry.resolve("t1", "play") == []
    assert registry.resolve("t1", "high-am") == []


def test_resolve_rejects_description_only_query(registry: OkfRegistry) -> None:
    registry.reload()
    assert registry.resolve("t1", "Flags transactions above the configured threshold") == []
    assert registry.resolve("t1", "Analyst steps for high-amount cases") == []


def test_shared_only_snapshot_revision_ignores_unrelated_tenant_updates(
    registry: OkfRegistry, tenant_root: Path
) -> None:
    registry.reload()
    shared_only_rev = registry.snapshot_revision("t-no-overlay")
    t1_rev = registry.snapshot_revision("t1")
    assert shared_only_rev != t1_rev

    t2 = tenant_root / "t2"
    t2.mkdir()
    (t2 / "index.md").write_text("---\nokf_version: \"0.1\"\n---\n")
    (t2 / "extra.md").write_text(
        _valid_frontmatter(
            concept_type="Reference",
            tenant_scope="t2",
            title="T2 Only Concept",
            source_hash_char="f",
        )
        + "Body.\n"
    )
    assert registry.reload().activated is True
    assert registry.snapshot_revision("t-no-overlay") == shared_only_rev
    assert registry.snapshot_revision("t2") != t1_rev


def test_t1_cannot_see_t2_concepts(registry: OkfRegistry, tenant_root: Path) -> None:
    t2 = tenant_root / "t2"
    t2.mkdir()
    (t2 / "index.md").write_text("# t2\n")
    (t2 / "secret.md").write_text(
        _valid_frontmatter(
            concept_type="Reference",
            tenant_scope="t2",
            title="T2 Secret Knowledge",
            source_hash_char="d",
        )
        + "Secret.\n"
    )
    registry.reload()
    hits = registry.resolve("t1", "T2 Secret")
    assert hits == []
    expanded = registry.expand("t1", ("secret",), max_depth=2, max_concepts=10)
    assert expanded == []


def test_tenant_concept_precedence_over_shared(
    registry: OkfRegistry, tenant_root: Path
) -> None:
    registry.reload()
    overlay = (
        _valid_frontmatter(
            concept_type="Fraud Rule",
            tenant_scope="t1",
            title="High Amount Rule",
            source_hash_char="e",
        )
        + "Tenant-specific override body.\n"
    )
    tenant_rule = tenant_root / "t1" / "rules" / "high-amount.md"
    tenant_rule.parent.mkdir(parents=True, exist_ok=True)
    tenant_rule.write_text(overlay)
    assert registry.reload().activated is True
    hits = registry.resolve("t1", "rules/high-amount")
    assert len(hits) == 1
    assert hits[0].authority == "tenant"
    assert "Tenant-specific" in hits[0].concept.body


def test_invalid_reload_keeps_prior_snapshot(registry: OkfRegistry, shared_root: Path) -> None:
    first = registry.reload()
    assert first.activated is True
    prior = registry.snapshot_revision("t1")
    (shared_root / "rules" / "high-amount.md").write_text("invalid")
    second = registry.reload()
    assert second.activated is False
    assert registry.snapshot_revision("t1") == prior
    hits = registry.resolve("t1", "High Amount Rule")
    assert any(h.concept.concept_id == "rules/high-amount" for h in hits)


def test_expand_bounded_cycle(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "index.md").write_text("---\nokf_version: \"0.1\"\n---\n")
    fm = _valid_frontmatter(
        concept_type="Reference", tenant_scope="shared", title="A", source_hash_char="1"
    )
    (shared / "a.md").write_text(fm + "Link [b](b.md).\n")
    (shared / "b.md").write_text(
        _valid_frontmatter(
            concept_type="Reference", tenant_scope="shared", title="B", source_hash_char="2"
        )
        + "Link [a](a.md).\n"
    )
    tenants = tmp_path / "tenants"
    tenants.mkdir()
    reg = OkfRegistry(shared_root=shared, tenant_root=tenants)
    reg.reload()
    hits = reg.expand("t1", ("a",), max_depth=5, max_concepts=10)
    ids = [h.concept.concept_id for h in hits]
    assert len(ids) <= 10
    assert len(set(ids)) == len(ids)
    assert "a" in ids and "b" in ids


def test_expand_respects_max_depth(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "index.md").write_text("---\nokf_version: \"0.1\"\n---\n")
    (shared / "c0.md").write_text(
        _valid_frontmatter(
            concept_type="Reference", tenant_scope="shared", title="C0", source_hash_char="3"
        )
        + "Next [c1](c1.md).\n"
    )
    (shared / "c1.md").write_text(
        _valid_frontmatter(
            concept_type="Reference", tenant_scope="shared", title="C1", source_hash_char="4"
        )
        + "Next [c2](c2.md).\n"
    )
    (shared / "c2.md").write_text(
        _valid_frontmatter(
            concept_type="Reference", tenant_scope="shared", title="C2", source_hash_char="5"
        )
        + "Leaf.\n"
    )
    tenants = tmp_path / "tenants"
    tenants.mkdir()
    reg = OkfRegistry(shared_root=shared, tenant_root=tenants)
    reg.reload()
    shallow = reg.expand("t1", ("c0",), max_depth=0, max_concepts=10)
    assert {h.concept.concept_id for h in shallow} == {"c0"}
    one_hop = reg.expand("t1", ("c0",), max_depth=1, max_concepts=10)
    assert {h.concept.concept_id for h in one_hop} == {"c0", "c1"}


def test_expand_respects_max_concepts(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "index.md").write_text("---\nokf_version: \"0.1\"\n---\n")
    (shared / "hub.md").write_text(
        _valid_frontmatter(
            concept_type="Reference", tenant_scope="shared", title="Hub", source_hash_char="6"
        )
        + "Links [a](a.md) [b](b.md) [c](c.md).\n"
    )
    for name in ("a", "b", "c"):
        (shared / f"{name}.md").write_text(
            _valid_frontmatter(
                concept_type="Reference",
                tenant_scope="shared",
                title=name.upper(),
                source_hash_char=name,
            )
            + f"{name} body.\n"
        )
    tenants = tmp_path / "tenants"
    tenants.mkdir()
    reg = OkfRegistry(shared_root=shared, tenant_root=tenants)
    reg.reload()
    hits = reg.expand("t1", ("hub",), max_depth=2, max_concepts=2)
    assert len(hits) == 2
