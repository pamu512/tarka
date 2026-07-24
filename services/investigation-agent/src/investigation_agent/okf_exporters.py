from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from investigation_agent.playbooks import _PLAYBOOKS

LANDMARK_CASE_ALLOWLIST = frozenset(
    {
        "case_id",
        "title",
        "typology_ids",
        "rule_ids",
        "disposition",
        "evidence_ids",
        "summary",
        "lessons",
        "approved_revision",
        "source_content_hash",
    }
)

_PII_KEY_HINTS = frozenset(
    {
        "email",
        "phone",
        "ssn",
        "name",
        "address",
        "ip_address",
        "account_number",
        "card_number",
    }
)

_STAGING_GOVERNANCE = {
    "approval_status": "proposed",
    "sensitivity": "internal",
    "tenant_scope": "shared",
}


class LandmarkCaseSanitizationError(ValueError):
    """Raised when landmark-case payloads contain disallowed or unsanitized fields."""


class StagingPathError(ValueError):
    """Raised when a write target is an active OKF bundle root."""


class OkfExportError(ValueError):
    """Raised when legacy source records cannot be exported deterministically."""


def source_record_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_concept(frontmatter: dict[str, Any], body: str) -> str:
    header = yaml.safe_dump(
        frontmatter,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{header}\n---\n{body.strip()}\n"


def merge_export_files(*file_maps: dict[str, str]) -> dict[str, str]:
    """Merge export path maps; duplicate paths raise deterministically."""
    merged: dict[str, str] = {}
    for files in file_maps:
        for rel_path, content in files.items():
            if rel_path in merged:
                raise OkfExportError(f"duplicate export path: {rel_path}")
            merged[rel_path] = content
    return dict(sorted(merged.items()))


def _pack_revision(pack: dict[str, Any]) -> str:
    return source_record_hash(pack)[:16]


def _rule_body(rule: dict[str, Any]) -> str:
    lines: list[str] = []
    description = str(rule.get("description") or "").strip()
    if description:
        lines.append(description)
        lines.append("")
    when = rule.get("when") or []
    if when:
        lines.append("**Conditions**")
        for clause in when:
            if isinstance(clause, dict):
                op = clause.get("op", "?")
                field = clause.get("field", "?")
                value = clause.get("value", "")
                lines.append(f"- `{field}` {op} `{value}`")
        lines.append("")
    any_tag = rule.get("any_tag")
    if any_tag:
        tags = ", ".join(f"`{t}`" for t in any_tag)
        lines.append(f"**Any tag**: {tags}")
        lines.append("")
    tags = rule.get("tags") or []
    if tags:
        tag_list = ", ".join(f"`{t}`" for t in tags)
        lines.append(f"**Tags**: {tag_list}")
        lines.append("")
    if "score_delta" in rule:
        lines.append(f"**Score delta**: {rule['score_delta']}")
    return "\n".join(lines).strip() or f"Rule `{rule.get('id', 'unknown')}`."


def _export_rules_from_collection(
    pack: dict[str, Any],
    source_uri: str,
    collection: str,
    revision: str,
) -> dict[str, str]:
    files: dict[str, str] = {}
    entries = pack.get(collection)
    if entries is None:
        return files
    if not isinstance(entries, list):
        raise OkfExportError(f"{source_uri}: {collection} must be a list")
    for index, rule in enumerate(entries):
        if not isinstance(rule, dict):
            raise OkfExportError(f"{source_uri}: {collection}[{index}] must be an object")
        rule_id = str(rule.get("id") or "").strip()
        if not rule_id:
            raise OkfExportError(f"{source_uri}: {collection}[{index}] missing id")
        rel_path = f"rules/{rule_id}.md"
        if rel_path in files:
            raise OkfExportError(f"duplicate export path: {rel_path}")
        title = str(rule.get("description") or rule_id).strip()
        tags = tuple(str(t).strip() for t in (rule.get("tags") or []) if str(t).strip())
        frontmatter = {
            "type": "Fraud Rule",
            "title": title[:256],
            "description": title[:512],
            "tags": list(tags),
            "source_uri": f"{source_uri}#{rule_id}",
            "source_content_hash": source_record_hash(rule),
            "approved_revision": revision,
            **_STAGING_GOVERNANCE,
        }
        files[rel_path] = render_concept(frontmatter, _rule_body(rule))
    return files


def export_rule_pack(pack: dict[str, Any], source_uri: str) -> dict[str, str]:
    """Export rules and tag_rules from a legacy pack into OKF concept files."""
    if not isinstance(pack, dict):
        raise OkfExportError(f"{source_uri}: pack must be an object")
    revision = _pack_revision(pack)
    return merge_export_files(
        _export_rules_from_collection(pack, source_uri, "rules", revision),
        _export_rules_from_collection(pack, source_uri, "tag_rules", revision),
    )


def export_typologies(payload: dict[str, Any], source_uri: str) -> dict[str, str]:
    """Export typology definitions with relative links to member rules."""
    if not isinstance(payload, dict):
        raise OkfExportError(f"{source_uri}: typologies payload must be an object")
    revision = source_record_hash(payload)[:16]
    files: dict[str, str] = {}
    typologies = payload.get("typologies")
    if typologies is None:
        return files
    if not isinstance(typologies, list):
        raise OkfExportError(f"{source_uri}: typologies must be a list")
    for index, typology in enumerate(typologies):
        if not isinstance(typology, dict):
            raise OkfExportError(f"{source_uri}: typologies[{index}] must be an object")
        typology_id = str(typology.get("id") or "").strip()
        if not typology_id:
            raise OkfExportError(f"{source_uri}: typologies[{index}] missing id")
        label = str(typology.get("label") or typology_id).strip()
        member_ids = [
            str(rid).strip()
            for rid in (typology.get("member_rule_ids") or [])
            if str(rid).strip()
        ]
        body_lines = [label, ""]
        if member_ids:
            body_lines.append("**Member rules**")
            for rule_id in sorted(member_ids):
                body_lines.append(f"- [{rule_id}](../rules/{rule_id}.md)")
            body_lines.append("")
        thresholds = typology.get("breach_thresholds")
        if isinstance(thresholds, dict) and thresholds:
            body_lines.append("**Breach thresholds**")
            for level in sorted(thresholds):
                body_lines.append(f"- {level}: {thresholds[level]}")
        frontmatter = {
            "type": "Fraud Typology",
            "title": label,
            "description": label,
            "tags": ["typology"],
            "source_uri": f"{source_uri}#{typology_id}",
            "source_content_hash": source_record_hash(typology),
            "approved_revision": revision,
            **_STAGING_GOVERNANCE,
        }
        rel_path = f"typologies/{typology_id}.md"
        if rel_path in files:
            raise OkfExportError(f"duplicate export path: {rel_path}")
        files[rel_path] = render_concept(frontmatter, "\n".join(body_lines).strip())
    return dict(sorted(files.items()))


def export_playbooks() -> dict[str, str]:
    """Export built-in investigation playbooks as shared OKF concepts."""
    revision = hashlib.sha256(
        "|".join(sorted(_PLAYBOOKS)).encode("utf-8")
    ).hexdigest()[:16]
    files: dict[str, str] = {}
    for playbook_id in sorted(_PLAYBOOKS):
        entry = _PLAYBOOKS[playbook_id]
        fragment = entry["fragment"].strip()
        title = entry["title"].strip()
        vertical = entry["vertical"].strip()
        record = {
            "id": playbook_id,
            "title": title,
            "vertical": vertical,
            "fragment": fragment,
        }
        frontmatter = {
            "type": "Investigation Playbook",
            "title": title,
            "description": f"{title} ({vertical})",
            "tags": ["playbook", vertical],
            "source_uri": f"playbooks/builtin#{playbook_id}",
            "source_content_hash": source_record_hash(record),
            "approved_revision": revision,
            **_STAGING_GOVERNANCE,
        }
        rel_path = f"playbooks/{playbook_id}.md"
        files[rel_path] = render_concept(frontmatter, fragment)
    return dict(sorted(files.items()))


def export_landmark_case(case: dict[str, Any], *, tenant_id: str) -> str:
    """Export a sanitized landmark case for a tenant overlay bundle."""
    if not isinstance(case, dict):
        raise LandmarkCaseSanitizationError("landmark case must be an object")
    extra = set(case) - LANDMARK_CASE_ALLOWLIST
    if extra:
        raise LandmarkCaseSanitizationError(
            f"landmark case contains disallowed fields: {','.join(sorted(extra))}"
        )
    for key in case:
        if key in _PII_KEY_HINTS:
            raise LandmarkCaseSanitizationError(
                f"landmark case contains unsanitized PII field: {key}"
            )
    case_id = str(case.get("case_id") or "").strip()
    if not case_id:
        raise LandmarkCaseSanitizationError("case_id is required")
    source_hash = str(case.get("source_content_hash") or "").strip().lower()
    if len(source_hash) != 64 or not all(c in "0123456789abcdef" for c in source_hash):
        raise LandmarkCaseSanitizationError("source_content_hash must be SHA-256 hex")

    typology_ids = case.get("typology_ids") or []
    rule_ids = case.get("rule_ids") or []
    evidence_ids = case.get("evidence_ids") or []
    body_lines = [
        str(case.get("summary") or "").strip(),
        "",
        "**Lessons**",
        str(case.get("lessons") or "").strip(),
        "",
    ]
    if typology_ids:
        body_lines.append("**Typologies**")
        for tid in sorted(str(x).strip() for x in typology_ids if str(x).strip()):
            body_lines.append(f"- [{tid}](/shared/typologies/{tid}.md)")
        body_lines.append("")
    if rule_ids:
        body_lines.append("**Rules**")
        for rid in sorted(str(x).strip() for x in rule_ids if str(x).strip()):
            body_lines.append(f"- [{rid}](/shared/rules/{rid}.md)")
        body_lines.append("")
    frontmatter = {
        "type": "Landmark Case",
        "title": str(case.get("title") or case_id).strip(),
        "description": str(case.get("summary") or "")[:512],
        "tags": ["landmark-case"],
        "source_uri": f"landmark-cases/{case_id}",
        "source_content_hash": source_hash,
        "approval_status": "proposed",
        "approved_revision": str(case.get("approved_revision") or "").strip(),
        "sensitivity": "internal",
        "tenant_scope": str(tenant_id).strip(),
        "evidence_ids": [str(x).strip() for x in evidence_ids if str(x).strip()],
    }
    return render_concept(frontmatter, "\n".join(body_lines).strip())


def assert_staging_output_path(output: Path, *, repo_root: Path) -> None:
    """Refuse writes to active shared or tenant OKF roots."""
    output_resolved = output.resolve()
    shared_active = (repo_root / "knowledge" / "shared").resolve()
    tenant_active = (repo_root / "knowledge" / "tenants").resolve()
    for active in (shared_active, tenant_active):
        if output_resolved == active or active in output_resolved.parents:
            raise StagingPathError(
                f"refusing to export to active OKF root: {active.as_posix()}"
            )


def write_staging_bundle(staging_root: Path, files: dict[str, str], *, repo_root: Path) -> None:
    """Write exported concepts only under the supplied staging root."""
    assert_staging_output_path(staging_root, repo_root=repo_root)
    staging_root = staging_root.resolve()
    staging_resolved = staging_root.resolve()
    for rel_path, content in sorted(files.items()):
        rel = Path(rel_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"invalid relative export path: {rel_path}")
        target = (staging_root / rel).resolve()
        if staging_resolved not in target.parents and target != staging_resolved:
            raise ValueError(f"export path escapes staging root: {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.endswith("\n"):
            normalized += "\n"
        target.write_text(normalized, encoding="utf-8", newline="\n")


def shared_bundle_index_md() -> str:
    return (
        "---\n"
        "okf_version: \"0.1\"\n"
        "---\n"
        "# Shared OKF bundle\n"
        "\n"
        "Approved shared fraud knowledge concepts.\n"
    )


def is_rule_pack_file(path: Path) -> bool:
    if path.suffix.lower() != ".json":
        return False
    name = path.name
    if name.startswith("pack_"):
        return False
    if name in {
        "typology_definitions_v1.json",
        "typology_predicate_registry_v1.json",
        "graph_routing_policy_v1.json",
        "integrity_tamper_policy_v1.json",
        "experiment_registry.json",
    }:
        return False
    return True


def collect_shared_exports(rules_dir: Path, *, include_playbooks: bool) -> dict[str, str]:
    """Build a shared staging bundle from legacy rule JSON on disk."""
    chunks: list[dict[str, str]] = [{"index.md": shared_bundle_index_md()}]
    for path in sorted(rules_dir.glob("*.json")):
        if not is_rule_pack_file(path):
            continue
        raw = path.read_text(encoding="utf-8")
        pack = json.loads(raw)
        if not isinstance(pack, dict):
            raise OkfExportError(f"rules/{path.name}: pack must be an object")
        if not (pack.get("rules") or pack.get("tag_rules")):
            continue
        source_uri = f"rules/{path.name}"
        chunks.append(export_rule_pack(pack, source_uri))

    typology_path = rules_dir / "typology_definitions_v1.json"
    if typology_path.is_file():
        typologies = json.loads(typology_path.read_text(encoding="utf-8"))
        chunks.append(
            export_typologies(typologies, "rules/typology_definitions_v1.json")
        )

    if include_playbooks:
        chunks.append(export_playbooks())

    return merge_export_files(*chunks)
