"""Deterministic OKF exporters and staging writes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from investigation_agent.okf_exporters import (
    LandmarkCaseSanitizationError,
    OkfExportError,
    StagingPathError,
    assert_staging_output_path,
    collect_shared_exports,
    export_landmark_case,
    export_landmark_case_bundle,
    export_playbooks,
    export_rule_pack,
    export_typologies,
    merge_export_files,
    render_concept,
    source_record_hash,
    write_staging_bundle,
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_REL_LINK = re.compile(r"\]\(([^)]+)\)")


def _frontmatter(md: str) -> dict:
    match = _FRONTMATTER.match(md)
    assert match, md
    meta = yaml.safe_load(match.group(1))
    assert isinstance(meta, dict)
    return meta


def test_render_concept_sorted_keys_and_trailing_newline():
    md = render_concept({"type": "Reference", "title": "T", "z_field": 1, "a_field": 2}, "body\n")
    assert md.endswith("\n")
    assert md.startswith("---\n")
    header = md.split("---\n")[1]
    assert "a_field" in header and header.index("a_field") < header.index("z_field")


def test_export_rule_pack_byte_identical_across_runs():
    pack = {
        "version": 1,
        "rules": [
            {
                "id": "sample_rule",
                "when": [{"op": "gte", "field": "amount", "value": 100}],
                "tags": ["high_value"],
                "score_delta": 10,
                "description": "Sample threshold",
            }
        ],
        "tag_rules": [],
    }
    first = export_rule_pack(pack, "rules/sample.json")
    second = export_rule_pack(pack, "rules/sample.json")
    assert first == second
    assert "rules/sample_rule.md" in first
    meta = _frontmatter(first["rules/sample_rule.md"])
    assert meta["source_uri"] == "rules/sample.json#sample_rule"
    assert meta["type"] == "Fraud Rule"
    assert meta["tenant_scope"] == "shared"
    assert meta["approval_status"] == "proposed"


def test_one_byte_source_change_alters_source_content_hash():
    rule_a = {
        "id": "r1",
        "when": [],
        "tags": [],
        "score_delta": 1,
        "description": "alpha",
    }
    rule_b = dict(rule_a)
    rule_b["description"] = "alphb"
    pack_a = {"version": 1, "rules": [rule_a], "tag_rules": []}
    pack_b = {"version": 1, "rules": [rule_b], "tag_rules": []}
    files_a = export_rule_pack(pack_a, "rules/a.json")
    files_b = export_rule_pack(pack_b, "rules/b.json")
    hash_a = _frontmatter(files_a["rules/r1.md"])["source_content_hash"]
    hash_b = _frontmatter(files_b["rules/r1.md"])["source_content_hash"]
    assert hash_a != hash_b
    assert (
        hashlib.sha256(files_a[f"_provenance/sources/{hash_a}.json"].encode()).hexdigest() == hash_a
    )
    assert (
        hashlib.sha256(files_b[f"_provenance/sources/{hash_b}.json"].encode()).hexdigest() == hash_b
    )


def test_typology_exports_relative_rule_links():
    payload = {
        "version": 1,
        "typologies": [
            {
                "id": "velocity_abuse",
                "label": "Velocity abuse",
                "member_rule_ids": ["velocity_high_1h", "velocity_high_24h"],
                "weight_per_rule_hit": 35,
                "breach_thresholds": {"warning": 40, "alert": 75},
            }
        ],
    }
    files = export_typologies(payload, "rules/typology_definitions_v1.json")
    body = files["typologies/velocity_abuse.md"].split("---\n", 2)[2]
    hrefs = _REL_LINK.findall(body)
    assert hrefs
    assert all(not h.startswith("/") and "://" not in h for h in hrefs)
    assert "../rules/velocity_high_1h.md" in hrefs


def test_export_playbooks_deterministic():
    first = export_playbooks()
    second = export_playbooks()
    assert first == second
    assert first
    sample = next(content for path, content in first.items() if path.endswith(".md"))
    meta = _frontmatter(sample)
    assert meta["type"] == "Investigation Playbook"
    assert meta["tenant_scope"] == "shared"


def test_landmark_case_rejects_unsanitized_pii():
    with pytest.raises(LandmarkCaseSanitizationError):
        export_landmark_case(
            {"case_id": "c1", "email": "person@example.com", "disposition": "fraud"},
            tenant_id="t1",
        )


def test_landmark_case_allowlist_only():
    case = {
        "case_id": "c1",
        "title": "Reviewed case",
        "typology_ids": ["velocity_abuse"],
        "rule_ids": ["velocity_high_1h"],
        "disposition": "fraud",
        "evidence_ids": ["ev-1"],
        "summary": "Sanitized summary.",
        "lessons": "Lesson learned.",
        "approved_revision": "rev-1",
        "source_content_hash": "c" * 64,
    }
    md = export_landmark_case(case, tenant_id="t1")
    meta = _frontmatter(md)
    assert meta["type"] == "Landmark Case"
    assert meta["tenant_scope"] == "t1"
    assert meta["approval_status"] == "proposed"
    assert "](/shared/typologies/velocity_abuse.md)" in md


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Escalation for analyst@example.test"),
        ("summary", "Call +1 (415) 555-0199 before closing."),
        ("lessons", "Card 4111 1111 1111 1111 was reused."),
        ("summary", "Account number 9988776655443322 was targeted."),
    ],
)
def test_landmark_case_rejects_pii_inside_allowed_text_fields(field, value):
    case = {
        "case_id": "c1",
        "title": "Reviewed case",
        "summary": "Sanitized summary.",
        "lessons": "Sanitized lesson.",
        "approved_revision": "rev-1",
        "source_content_hash": "c" * 64,
    }
    case[field] = value

    with pytest.raises(LandmarkCaseSanitizationError, match="PII"):
        export_landmark_case(case, tenant_id="t1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("disposition", "fraud linked to 123-45-6789"),
        ("approved_revision", "reviewed from 192.0.2.44"),
        ("typology_ids", ["activity at 742 Evergreen Street"]),
        ("rule_ids", ["customer name: Jane Example"]),
        ("evidence_ids", ["IBAN GB82 WEST 1234 5698 7654 32"]),
        ("summary", "national id: AB-123456789"),
        ("lessons", "mobile: +44 20 7946 0958"),
    ],
)
def test_landmark_case_scans_every_accepted_textual_value(field, value):
    case = {
        "case_id": "case-opaque-17",
        "title": "Reviewed case",
        "summary": "Sanitized summary.",
        "lessons": "Sanitized lesson.",
        "disposition": "fraud",
        "approved_revision": "rev-1",
        "source_content_hash": "c" * 64,
    }
    case[field] = value

    with pytest.raises(LandmarkCaseSanitizationError, match="PII"):
        export_landmark_case(case, tenant_id="t1")


@pytest.mark.parametrize(
    "case_id",
    [
        "../case-1",
        "case/one",
        "case one",
        "person@example.test",
        "123-45-6789",
        "",
    ],
)
def test_landmark_case_requires_safe_opaque_case_id(case_id):
    with pytest.raises(LandmarkCaseSanitizationError, match="case_id"):
        export_landmark_case(
            {
                "case_id": case_id,
                "title": "Reviewed case",
                "source_content_hash": "c" * 64,
            },
            tenant_id="t1",
        )


def test_landmark_case_allows_normal_fraud_terminology():
    md = export_landmark_case(
        {
            "case_id": "case-opaque-18",
            "title": "Account takeover velocity review",
            "summary": "Payment fraud indicators triggered device and account review.",
            "lessons": "Review card-present risk and customer profile consistency.",
            "disposition": "confirmed_fraud",
            "typology_ids": ["account_takeover"],
            "rule_ids": ["payment_velocity"],
            "evidence_ids": ["ev-pseudonymous-12"],
            "approved_revision": "rev-2",
            "source_content_hash": "d" * 64,
        },
        tenant_id="t1",
    )

    assert "Account takeover velocity review" in md


def test_landmark_case_rejects_unlabeled_domestic_phone():
    with pytest.raises(LandmarkCaseSanitizationError, match="phone"):
        export_landmark_case(
            {
                "case_id": "case-opaque-19",
                "title": "Reviewed case",
                "summary": "Escalate to 415-555-0199 before disposition.",
                "source_content_hash": "e" * 64,
            },
            tenant_id="t1",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Jane Example"),
        ("summary", "Reviewed by Jane Example"),
        ("lessons", "Jane Example confirmed the pattern"),
        ("evidence_ids", ["Jane Example"]),
    ],
)
def test_landmark_case_rejects_likely_unlabeled_person_names(field, value):
    case = {
        "case_id": "case-opaque-20",
        "title": "Reviewed case",
        "summary": "Sanitized summary.",
        "lessons": "Sanitized lesson.",
        "source_content_hash": "f" * 64,
    }
    case[field] = value

    with pytest.raises(LandmarkCaseSanitizationError, match="person_name"):
        export_landmark_case(case, tenant_id="t1")


def test_landmark_case_person_name_allowlist_keeps_fraud_domain_phrases():
    md = export_landmark_case(
        {
            "case_id": "case-opaque-21",
            "title": "Friendly Fraud",
            "summary": "High Amount review with Account Takeover indicators.",
            "lessons": "Payment Fraud controls require Manual Review.",
            "source_content_hash": "a" * 64,
        },
        tenant_id="t1",
    )

    assert "Friendly Fraud" in md
    assert "High Amount" in md


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Call 4155550199"),
        ("summary", "Escalate to 4155550199"),
        ("lessons", "4155550199"),
        ("typology_ids", ["4155550199"]),
        ("rule_ids", ["4155550199"]),
        ("evidence_ids", ["4155550199"]),
    ],
)
def test_landmark_case_rejects_compact_domestic_phone_across_fields(field, value):
    case = {
        "case_id": "case-opaque-compact-phone",
        "title": "Reviewed case",
        "summary": "Sanitized summary.",
        "lessons": "Sanitized lesson.",
        "source_content_hash": "b" * 64,
    }
    case[field] = value

    with pytest.raises(LandmarkCaseSanitizationError, match="phone"):
        export_landmark_case(case, tenant_id="t1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "JANE EXAMPLE"),
        ("summary", "jane example"),
        ("lessons", "Reviewed by JANE EXAMPLE"),
        ("typology_ids", ["jane example"]),
        ("rule_ids", ["JANE EXAMPLE"]),
        ("evidence_ids", ["jane example"]),
    ],
)
def test_landmark_case_rejects_case_normalized_person_names(field, value):
    case = {
        "case_id": "case-opaque-normalized-name",
        "title": "Reviewed case",
        "summary": "Sanitized summary.",
        "lessons": "Sanitized lesson.",
        "source_content_hash": "c" * 64,
    }
    case[field] = value

    with pytest.raises(LandmarkCaseSanitizationError, match="person_name"):
        export_landmark_case(case, tenant_id="t1")


@pytest.mark.parametrize(
    "phrase",
    [
        "Money Mule",
        "money mule",
        "Friendly Fraud",
        "friendly fraud",
        "High Amount",
        "high amount",
        "Account Takeover",
        "Manual Review",
        "Payment Velocity",
    ],
)
def test_landmark_case_central_domain_vocabulary_allows_playbook_terms(phrase):
    export_landmark_case(
        {
            "case_id": "case-opaque-domain-vocabulary",
            "title": phrase,
            "summary": f"{phrase} pattern.",
            "lessons": f"{phrase} controls.",
            "source_content_hash": "d" * 64,
        },
        tenant_id="t1",
    )


def test_compact_phone_guard_does_not_treat_luhn_or_date_like_ids_as_phone():
    export_landmark_case(
        {
            "case_id": "case-opaque-numeric-guards",
            "title": "Reviewed case",
            "summary": "Batch 2026072401 and card 79927398713 were pseudonymized.",
            "evidence_ids": ["batch-2026072401", "token-79927398713"],
            "source_content_hash": "e" * 64,
        },
        tenant_id="t1",
    )


def _write_exported_landmark(root: Path, files: dict[str, str]) -> None:
    for rel_path, content in files.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel_path.endswith(".md"):
            content = content.replace("approval_status: proposed", "approval_status: approved")
        path.write_text(content, encoding="utf-8")


def test_complete_landmark_export_has_independent_validated_provenance(tmp_path):
    from investigation_agent.okf_parser import validate_bundle

    files = export_landmark_case_bundle(
        {
            "case_id": "case-opaque-22",
            "title": "High Amount Review",
            "summary": "Sanitized transaction pattern.",
            "lessons": "Manual Review remains required.",
            "disposition": "confirmed_fraud",
            "evidence_ids": ["ev-pseudonymous-22"],
            "approved_revision": "rev-22",
        },
        tenant_id="t1",
    )
    manifest = json.loads(files["source-manifest.json"])
    entry = manifest["sources"]["landmark-cases/case-opaque-22"]
    snapshot_path = entry["snapshot_path"]
    snapshot = files[snapshot_path]
    concept = files["landmark-cases/case-opaque-22.md"]

    assert hashlib.sha256(snapshot.encode("utf-8")).hexdigest() == entry["source_content_hash"]
    assert _frontmatter(concept)["source_content_hash"] == entry["source_content_hash"]
    assert json.loads(snapshot)["record"]["summary"] == "Sanitized transaction pattern."

    root = tmp_path / "t1"
    _write_exported_landmark(root, files)
    result = validate_bundle(root, scope="tenant", tenant_id="t1")
    assert result.valid is True, result.issues


@pytest.mark.parametrize("mutation", ["tamper", "missing"])
def test_complete_landmark_export_rejects_tampered_or_missing_snapshot(tmp_path, mutation):
    from investigation_agent.okf_parser import validate_bundle

    files = export_landmark_case_bundle(
        {
            "case_id": "case-opaque-23",
            "title": "Reviewed case",
            "summary": "Sanitized pattern.",
            "lessons": "Manual Review.",
            "approved_revision": "rev-23",
        },
        tenant_id="t1",
    )
    manifest = json.loads(files["source-manifest.json"])
    snapshot_path = manifest["sources"]["landmark-cases/case-opaque-23"]["snapshot_path"]
    root = tmp_path / mutation / "t1"
    _write_exported_landmark(root, files)
    snapshot = root / snapshot_path
    if mutation == "tamper":
        snapshot.write_text(snapshot.read_text(encoding="utf-8") + " ", encoding="utf-8")
    else:
        snapshot.unlink()

    result = validate_bundle(root, scope="tenant", tenant_id="t1")

    assert result.valid is False
    assert {"source_snapshot_hash_mismatch", "source_snapshot_missing"} & {
        issue.code for issue in result.issues
    }


def test_merge_export_files_raises_on_duplicate_paths():
    with pytest.raises(OkfExportError, match="duplicate export path"):
        merge_export_files(
            {"rules/r1.md": "a"},
            {"rules/r1.md": "b"},
        )


def test_export_rule_pack_rejects_duplicate_ids_within_pack():
    pack = {
        "version": 1,
        "rules": [
            {"id": "dup", "when": [], "tags": [], "score_delta": 1},
            {"id": "dup", "when": [], "tags": [], "score_delta": 2},
        ],
        "tag_rules": [],
    }
    with pytest.raises(OkfExportError, match="duplicate export path"):
        export_rule_pack(pack, "rules/a.json")


def test_collect_shared_exports_rejects_duplicate_rule_across_packs(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "a.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [{"id": "shared_id", "when": [], "tags": [], "score_delta": 1}],
                "tag_rules": [],
            }
        )
    )
    (rules_dir / "b.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [{"id": "shared_id", "when": [], "tags": [], "score_delta": 2}],
                "tag_rules": [],
            }
        )
    )
    with pytest.raises(OkfExportError, match="duplicate export path"):
        collect_shared_exports(rules_dir, include_playbooks=False)


def test_export_rule_pack_rejects_malformed_rule(tmp_path):
    with pytest.raises(OkfExportError, match="must be an object"):
        export_rule_pack({"version": 1, "rules": ["bad"], "tag_rules": []}, "rules/x.json")
    with pytest.raises(OkfExportError, match="missing id"):
        export_rule_pack(
            {"version": 1, "rules": [{"when": [], "tags": [], "score_delta": 1}], "tag_rules": []},
            "rules/x.json",
        )


def test_export_typologies_rejects_malformed_entry():
    with pytest.raises(OkfExportError, match="must be an object"):
        export_typologies({"typologies": [1]}, "rules/t.json")
    with pytest.raises(OkfExportError, match="missing id"):
        export_typologies({"typologies": [{"label": "x"}]}, "rules/t.json")


def test_write_staging_bundle_refuses_active_shared_root(tmp_path):
    repo = tmp_path / "repo"
    active = repo / "knowledge" / "shared"
    active.mkdir(parents=True)
    with pytest.raises(ValueError, match="active"):
        assert_staging_output_path(active, repo_root=repo)


def test_write_staging_bundle_writes_only_under_root(tmp_path):
    staging = tmp_path / "var" / "okf-staging" / "shared"
    files = {
        "index.md": "---\nokf_version: '0.1'\n---\n# Staging\n",
        "rules/r1.md": render_concept(
            {
                "type": "Fraud Rule",
                "title": "R1",
                "source_uri": "rules/x.json#r1",
                "source_content_hash": "a" * 64,
                "approval_status": "approved",
                "approved_revision": "rev",
                "sensitivity": "internal",
                "tenant_scope": "shared",
            },
            "Body.",
        ),
    }
    write_staging_bundle(staging, files, repo_root=tmp_path)
    assert (staging / "rules" / "r1.md").read_text(encoding="utf-8") == files["rules/r1.md"]


def test_write_staging_bundle_replaces_output_and_removes_obsolete_files(tmp_path):
    staging = tmp_path / "var" / "okf-staging" / "shared"
    write_staging_bundle(
        staging,
        {"index.md": "# first\n", "rules/obsolete.md": "obsolete\n"},
        repo_root=tmp_path,
    )

    write_staging_bundle(
        staging,
        {"index.md": "# second\n", "rules/current.md": "current\n"},
        repo_root=tmp_path,
    )

    assert not (staging / "rules" / "obsolete.md").exists()
    assert (staging / "rules" / "current.md").read_text() == "current\n"


def test_staging_guard_honors_configured_active_roots(tmp_path, monkeypatch):
    configured_shared = tmp_path / "mounted" / "shared"
    configured_tenants = tmp_path / "mounted" / "tenants"
    monkeypatch.setenv("OKF_SHARED_ROOT", str(configured_shared))
    monkeypatch.setenv("OKF_TENANT_ROOT", str(configured_tenants))

    for active in (configured_shared, configured_tenants / "t1"):
        with pytest.raises(StagingPathError, match="active"):
            assert_staging_output_path(active, repo_root=tmp_path)


def test_collect_shared_exports_generates_deterministic_source_manifest(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "sample.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "r1",
                        "description": "Sample",
                        "when": [{"field": "amount", "op": "gte", "value": 10}],
                    }
                ],
            }
        )
    )

    first = collect_shared_exports(rules_dir, include_playbooks=False)
    second = collect_shared_exports(rules_dir, include_playbooks=False)
    manifest = json.loads(first["source-manifest.json"])

    assert first == second
    assert manifest["schema_id"] == "tarka.okf_source_manifest/v1"
    source = manifest["sources"]["rules/sample.json#r1"]
    assert source["snapshot_path"].startswith("_provenance/sources/")
    snapshot = first[source["snapshot_path"]].encode()
    assert hashlib.sha256(snapshot).hexdigest() == source["source_content_hash"]
    assert (
        source["source_content_hash"] == _frontmatter(first["rules/r1.md"])["source_content_hash"]
    )


def test_source_record_hash_stable_json():
    record = {"b": 2, "a": 1}
    expected = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    assert source_record_hash(record) == expected
