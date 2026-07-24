"""OKF v0.1 concept parsing and bundle validation."""

from pathlib import Path

from investigation_agent.okf_parser import parse_concept, validate_bundle


def test_parse_concept_identity_and_links(tmp_path):
    root = tmp_path / "shared"
    (root / "rules").mkdir(parents=True)
    (root / "rules" / "r1.md").write_text(
        "---\n"
        "type: Fraud Rule\n"
        "title: High amount\n"
        "source_uri: rules/default.json#r1\n"
        "source_content_hash: " + "a" * 64 + "\n"
        "approval_status: approved\n"
        "approved_revision: abc123\n"
        "sensitivity: internal\n"
        "tenant_scope: shared\n"
        "---\n"
        "Use [the playbook](../playbooks/review.md).\n"
    )
    concept = parse_concept(root / "rules" / "r1.md", root, "shared", None)
    assert concept.concept_id == "rules/r1"
    assert concept.links == ("playbooks/review",)


def test_reject_path_traversal_link(tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    (root / "bad.md").write_text(
        "---\ntype: Reference\ntenant_scope: shared\n"
        "source_uri: docs/bad\nsource_content_hash: " + "b" * 64 + "\n"
        "approval_status: approved\napproved_revision: abc123\n"
        "sensitivity: internal\n---\n[escape](../../outside.md)\n"
    )
    result = validate_bundle(root, scope="shared", tenant_id=None)
    assert result.valid is False
    assert "link_outside_bundle" in {issue.code for issue in result.issues}


def test_reject_cross_tenant_scope(tmp_path):
    root = tmp_path / "t1"
    root.mkdir()
    (root / "bad.md").write_text(
        "---\ntype: Playbook\ntenant_scope: t2\n"
        "source_uri: playbooks/bad\nsource_content_hash: " + "c" * 64 + "\n"
        "approval_status: approved\napproved_revision: abc123\n"
        "sensitivity: internal\n---\nBad scope.\n"
    )
    result = validate_bundle(root, scope="tenant", tenant_id="t1")
    assert result.valid is False
    assert "tenant_scope_mismatch" in {issue.code for issue in result.issues}


def test_unknown_type_is_valid_generic_concept(tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    (root / "custom.md").write_text(
        "---\ntype: Custom Fraud Knowledge\ntenant_scope: shared\n"
        "source_uri: docs/custom\nsource_content_hash: " + "d" * 64 + "\n"
        "approval_status: approved\napproved_revision: abc123\n"
        "sensitivity: internal\n---\nCustom body.\n"
    )
    result = validate_bundle(root, scope="shared", tenant_id=None)
    assert result.valid is True
    assert result.bundle is not None
    assert result.bundle.concepts["custom"].concept_type == "Custom Fraud Knowledge"


def _valid_shared_frontmatter(source_hash_char: str = "e") -> str:
    return (
        "---\n"
        "type: Reference\n"
        "tenant_scope: shared\n"
        f"source_uri: docs/x\nsource_content_hash: {source_hash_char * 64}\n"
        "approval_status: approved\napproved_revision: abc123\n"
        "sensitivity: internal\n---\n"
    )


def test_reports_link_target_missing_alongside_other_issues(tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    (root / "scoped.md").write_text(
        "---\ntype: Playbook\ntenant_scope: wrong\n"
        "source_uri: playbooks/scoped\nsource_content_hash: " + "f" * 64 + "\n"
        "approval_status: approved\napproved_revision: abc123\n"
        "sensitivity: internal\n---\nScoped.\n"
    )
    (root / "linker.md").write_text(_valid_shared_frontmatter("a") + "See [missing](ghost.md).\n")
    result = validate_bundle(root, scope="shared", tenant_id=None)
    codes = {issue.code for issue in result.issues}
    assert result.valid is False
    assert result.bundle is None
    assert codes == {"tenant_scope_mismatch", "link_target_missing"}


def test_reject_duplicate_concept_id(tmp_path, monkeypatch):
    from investigation_agent import okf_parser as okf_parser_mod

    root = tmp_path / "shared"
    root.mkdir()
    path = root / "rules" / "r1.md"
    path.parent.mkdir()
    path.write_text(
        _valid_shared_frontmatter("b").replace("type: Reference", "type: Fraud Rule") + "Body.\n"
    )

    def _duplicate_paths(bundle_root: Path) -> list[Path]:
        assert bundle_root.resolve() == root.resolve()
        return [path, path]

    monkeypatch.setattr(okf_parser_mod, "_iter_concept_paths", _duplicate_paths)
    result = validate_bundle(root, scope="shared", tenant_id=None)
    assert result.valid is False
    assert result.bundle is None
    assert {issue.code for issue in result.issues} == {"duplicate_concept_id"}


def test_reject_frontmatter_on_reserved_index(tmp_path):
    root = tmp_path / "shared"
    (root / "rules").mkdir(parents=True)
    (root / "rules" / "index.md").write_text('---\nokf_version: "0.1"\n---\n# Rules\n')
    (root / "rules" / "r1.md").write_text(
        _valid_shared_frontmatter("c").replace("type: Reference", "type: Fraud Rule")
        + "Rule body.\n"
    )
    result = validate_bundle(root, scope="shared", tenant_id=None)
    assert result.valid is False
    assert result.bundle is None
    assert "frontmatter_on_reserved" in {issue.code for issue in result.issues}


def _approved_fm(
    *,
    concept_type: str = "Reference",
    tenant_scope: str = "shared",
    source_hash_char: str = "a",
) -> str:
    return (
        "---\n"
        f"type: {concept_type}\n"
        f"tenant_scope: {tenant_scope}\n"
        f"source_uri: docs/x\nsource_content_hash: {source_hash_char * 64}\n"
        "approval_status: approved\napproved_revision: abc123\n"
        "sensitivity: internal\n---\n"
    )


def test_reject_proposed_approval_status(tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    (root / "pending.md").write_text(
        _approved_fm().replace("approval_status: approved", "approval_status: proposed")
        + "Pending concept.\n"
    )
    result = validate_bundle(root, scope="shared", tenant_id=None)
    assert result.valid is False
    assert "approval_status_not_approved" in {issue.code for issue in result.issues}


def test_shared_rejects_logical_shared_links(tmp_path):
    root = tmp_path / "shared"
    (root / "rules").mkdir(parents=True)
    (root / "rules" / "r1.md").write_text(
        _approved_fm(concept_type="Fraud Rule", source_hash_char="1")
        + "See [shared rule](/shared/rules/r2.md).\n"
    )
    result = validate_bundle(root, scope="shared", tenant_id=None)
    assert result.valid is False
    assert "link_not_relative" in {issue.code for issue in result.issues}


def test_tenant_resolves_shared_logical_link(tmp_path):
    shared = tmp_path / "shared"
    tenant = tmp_path / "t1"
    (shared / "rules").mkdir(parents=True)
    (tenant / "playbooks").mkdir(parents=True)
    (shared / "index.md").write_text('---\nokf_version: "0.1"\n---\n')
    (shared / "rules" / "high-amount.md").write_text(
        _approved_fm(concept_type="Fraud Rule", source_hash_char="2") + "Shared rule body.\n"
    )
    (tenant / "index.md").write_text('---\nokf_version: "0.1"\n---\n')
    (tenant / "playbooks" / "review.md").write_text(
        _approved_fm(
            concept_type="Investigation Playbook",
            tenant_scope="t1",
            source_hash_char="3",
        )
        + "Follow [high amount](/shared/rules/high-amount.md).\n"
    )
    shared_bundle = validate_bundle(shared, scope="shared", tenant_id=None).bundle
    assert shared_bundle is not None
    result = validate_bundle(tenant, scope="tenant", tenant_id="t1", shared_bundle=shared_bundle)
    assert result.valid is True
    assert result.bundle is not None
    concept = result.bundle.concepts["playbooks/review"]
    assert concept.links == ("rules/high-amount",)


def test_tenant_rejects_shared_logical_escape(tmp_path):
    shared = tmp_path / "shared"
    tenant = tmp_path / "t1"
    shared.mkdir()
    tenant.mkdir()
    (shared / "index.md").write_text('---\nokf_version: "0.1"\n---\n')
    (tenant / "bad.md").write_text(
        _approved_fm(tenant_scope="t1", source_hash_char="4")
        + "Bad [escape](/shared/../outside.md).\n"
    )
    shared_bundle = validate_bundle(shared, scope="shared", tenant_id=None).bundle
    result = validate_bundle(tenant, scope="tenant", tenant_id="t1", shared_bundle=shared_bundle)
    assert result.valid is False
    assert "link_outside_bundle" in {issue.code for issue in result.issues}


def test_tenant_rejects_missing_shared_logical_target(tmp_path):
    shared = tmp_path / "shared"
    tenant = tmp_path / "t1"
    shared.mkdir()
    tenant.mkdir()
    (shared / "index.md").write_text('---\nokf_version: "0.1"\n---\n')
    (tenant / "bad.md").write_text(
        _approved_fm(tenant_scope="t1", source_hash_char="5")
        + "Missing [rule](/shared/rules/missing.md).\n"
    )
    shared_bundle = validate_bundle(shared, scope="shared", tenant_id=None).bundle
    result = validate_bundle(tenant, scope="tenant", tenant_id="t1", shared_bundle=shared_bundle)
    assert result.valid is False
    assert "link_target_missing" in {issue.code for issue in result.issues}


def test_tenant_rejects_absolute_non_shared_link(tmp_path):
    shared = tmp_path / "shared"
    tenant = tmp_path / "t1"
    shared.mkdir()
    tenant.mkdir()
    (shared / "index.md").write_text('---\nokf_version: "0.1"\n---\n')
    (tenant / "bad.md").write_text(
        _approved_fm(tenant_scope="t1", source_hash_char="6")
        + "Bad [/etc/passwd](/secrets/leak.md).\n"
    )
    shared_bundle = validate_bundle(shared, scope="shared", tenant_id=None).bundle
    result = validate_bundle(tenant, scope="tenant", tenant_id="t1", shared_bundle=shared_bundle)
    assert result.valid is False
    assert "link_not_shared_logical" in {issue.code for issue in result.issues}
