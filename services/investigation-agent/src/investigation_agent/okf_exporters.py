from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import tempfile
import uuid
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
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EMAIL_VALUE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_VALUE = re.compile(
    r"\b(?:phone|mobile|telephone|tel)\s*(?:number|no\.?|#)?\s*[:=-]?\s*"
    r"(?:\+?\d[\s().-]*){7,15}(?!\w)",
    re.IGNORECASE,
)
_DOMESTIC_PHONE_VALUE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
)
_COMPACT_DOMESTIC_PHONE_VALUE = re.compile(
    r"(?<![A-Za-z0-9])(?:1)?[2-9]\d{2}[2-9]\d{2}\d{4}(?![A-Za-z0-9])"
)
_INTERNATIONAL_PHONE_VALUE = re.compile(r"(?<!\w)\+\d(?:[\s().-]*\d){7,14}(?!\w)")
_ACCOUNT_VALUE = re.compile(
    r"\b(?:account|acct|card|routing|payment)\s*(?:number|no\.?|#|id)\s*"
    r"[:=-]?\s*[A-Z0-9][A-Z0-9 -]{5,30}\b",
    re.IGNORECASE,
)
_IBAN_VALUE = re.compile(
    r"\bIBAN\s*[:=-]?\s*[A-Z]{2}\d{2}(?:[\s-]?[A-Z0-9]){11,30}\b", re.IGNORECASE
)
_CARD_VALUE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_SSN_VALUE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_NATIONAL_ID_VALUE = re.compile(
    r"\b(?:ssn|social security|national id|national identification|tax id|passport|aadhaar|pan)"
    r"\s*(?:number|no\.?|#)?\s*[:=-]\s*[A-Z0-9][A-Z0-9 -]{5,24}\b",
    re.IGNORECASE,
)
_IP_VALUE = re.compile(
    r"(?<![A-F0-9:])(?:\d{1,3}\.){3}\d{1,3}(?![A-F0-9:.])"
    r"|(?<![A-F0-9:])(?:[A-F0-9]{1,4}:){2,7}[A-F0-9]{1,4}(?![A-F0-9:])",
    re.IGNORECASE,
)
_STREET_ADDRESS_VALUE = re.compile(
    r"\b\d{1,6}\s+[A-Z0-9][A-Z0-9 .'-]{1,48}\s+"
    r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|boulevard|blvd\.?|lane|ln\.?|"
    r"drive|dr\.?|court|ct\.?|way)\b",
    re.IGNORECASE,
)
_PERSON_NAME_VALUE = re.compile(
    r"\b(?:person|customer|cardholder|applicant|beneficiary|full\s+name|name)"
    r"\s*(?:name)?\s*[:=-]\s*[A-Z][A-Za-z'-]{1,30}"
    r"(?:\s+[A-Z][A-Za-z'-]{1,30}){1,3}\b",
    re.IGNORECASE,
)
# Deliberately excludes ambiguous English words that are also frequent names
# (for example: bill, mark, will, may, grant, chase, and dean).
_COMMON_GIVEN_NAMES = frozenset(
    {
        "aaron",
        "abdul",
        "adam",
        "adrian",
        "ahmed",
        "aisha",
        "alan",
        "alexander",
        "alice",
        "ali",
        "alison",
        "amanda",
        "amber",
        "amir",
        "amy",
        "ananya",
        "andrew",
        "angela",
        "anita",
        "anna",
        "anthony",
        "arjun",
        "arthur",
        "ashley",
        "barbara",
        "benjamin",
        "bethany",
        "betty",
        "beverly",
        "brenda",
        "brian",
        "brittany",
        "bruce",
        "carl",
        "carol",
        "caroline",
        "catherine",
        "charles",
        "charlotte",
        "cheryl",
        "christine",
        "christopher",
        "cynthia",
        "daniel",
        "david",
        "deborah",
        "debra",
        "deepak",
        "denise",
        "diana",
        "diane",
        "donna",
        "dorothy",
        "douglas",
        "dylan",
        "edward",
        "elizabeth",
        "emily",
        "emma",
        "eric",
        "ethan",
        "eugene",
        "evelyn",
        "fatima",
        "frank",
        "gabriel",
        "gary",
        "george",
        "gloria",
        "gregory",
        "hannah",
        "harold",
        "hassan",
        "heather",
        "helen",
        "henry",
        "ibrahim",
        "imran",
        "isabella",
        "jack",
        "jacob",
        "james",
        "jane",
        "janet",
        "jason",
        "jean",
        "jeffrey",
        "jennifer",
        "jeremy",
        "jerry",
        "jessica",
        "joan",
        "joe",
        "jose",
        "joseph",
        "joshua",
        "joyce",
        "juan",
        "judith",
        "julia",
        "julie",
        "justin",
        "karen",
        "katherine",
        "kathleen",
        "kathryn",
        "kayla",
        "keith",
        "kenneth",
        "kevin",
        "kimberly",
        "kyle",
        "lakshmi",
        "laura",
        "lawrence",
        "linda",
        "lisa",
        "lori",
        "luis",
        "madison",
        "margaret",
        "maria",
        "marie",
        "marilyn",
        "martha",
        "mary",
        "matthew",
        "megan",
        "melissa",
        "michael",
        "michelle",
        "mohammed",
        "muhammad",
        "nancy",
        "natalie",
        "nicholas",
        "nicole",
        "noah",
        "olivia",
        "pamela",
        "patricia",
        "paul",
        "peter",
        "priya",
        "rachel",
        "rajesh",
        "ravi",
        "raymond",
        "rebecca",
        "richard",
        "robert",
        "rohit",
        "ronald",
        "roy",
        "russell",
        "ruth",
        "ryan",
        "samantha",
        "samuel",
        "sandra",
        "sanjay",
        "sara",
        "sarah",
        "scott",
        "sharon",
        "shirley",
        "sophia",
        "stephanie",
        "stephen",
        "steven",
        "sunita",
        "susan",
        "teresa",
        "theresa",
        "thomas",
        "tiffany",
        "timothy",
        "tyler",
        "victoria",
        "vijay",
        "vincent",
        "virginia",
        "walter",
        "wayne",
        "william",
    }
)
_SOURCE_MANIFEST_NAME = "source-manifest.json"
_SOURCE_MANIFEST_SCHEMA = "tarka.okf_source_manifest/v1"
_SOURCE_SNAPSHOT_SCHEMA = "tarka.okf_source_snapshot/v1"
_SOURCE_SNAPSHOT_ROOT = "_provenance/sources"
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)

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


def _canonical_source_snapshot(source_uri: str, record: dict[str, Any]) -> str:
    return (
        json.dumps(
            {
                "schema_id": _SOURCE_SNAPSHOT_SCHEMA,
                "source_uri": source_uri,
                "record": record,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


def _source_snapshot(source_uri: str, record: dict[str, Any]) -> tuple[str, str, str]:
    content = _canonical_source_snapshot(source_uri, record)
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    path = f"{_SOURCE_SNAPSHOT_ROOT}/{source_hash}.json"
    return path, content, source_hash


def render_concept(frontmatter: dict[str, Any], body: str) -> str:
    header = yaml.safe_dump(
        frontmatter,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{header}\n---\n{body.strip()}\n"


def render_source_manifest(files: dict[str, str]) -> str:
    """Render provenance from canonical source snapshots, independently of concepts."""
    sources: dict[str, dict[str, str]] = {}
    for rel_path, content in sorted(files.items()):
        if not rel_path.startswith(f"{_SOURCE_SNAPSHOT_ROOT}/") or not rel_path.endswith(".json"):
            continue
        try:
            snapshot = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OkfExportError(f"{rel_path}: source snapshot is not valid JSON") from exc
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("schema_id") != _SOURCE_SNAPSHOT_SCHEMA
            or not isinstance(snapshot.get("record"), dict)
        ):
            raise OkfExportError(f"{rel_path}: source snapshot schema is invalid")
        source_uri = str(snapshot.get("source_uri") or "").strip()
        if not source_uri:
            raise OkfExportError(f"{rel_path}: source snapshot URI missing")
        if source_uri in sources:
            raise OkfExportError(f"duplicate source provenance: {source_uri}")
        source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if Path(rel_path).stem != source_hash:
            raise OkfExportError(f"{rel_path}: source snapshot path/hash mismatch")
        sources[source_uri] = {
            "snapshot_path": rel_path,
            "source_content_hash": source_hash,
        }
    payload = {
        "schema_id": _SOURCE_MANIFEST_SCHEMA,
        "sources": sources,
    }
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


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
        record_uri = f"{source_uri}#{rule_id}"
        snapshot_path, snapshot_content, snapshot_hash = _source_snapshot(record_uri, rule)
        frontmatter = {
            "type": "Fraud Rule",
            "title": title[:256],
            "description": title[:512],
            "tags": list(tags),
            "source_uri": record_uri,
            "source_content_hash": snapshot_hash,
            "approved_revision": revision,
            **_STAGING_GOVERNANCE,
        }
        files[rel_path] = render_concept(frontmatter, _rule_body(rule))
        files[snapshot_path] = snapshot_content
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
            str(rid).strip() for rid in (typology.get("member_rule_ids") or []) if str(rid).strip()
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
        record_uri = f"{source_uri}#{typology_id}"
        snapshot_path, snapshot_content, snapshot_hash = _source_snapshot(record_uri, typology)
        frontmatter = {
            "type": "Fraud Typology",
            "title": label,
            "description": label,
            "tags": ["typology"],
            "source_uri": record_uri,
            "source_content_hash": snapshot_hash,
            "approved_revision": revision,
            **_STAGING_GOVERNANCE,
        }
        rel_path = f"typologies/{typology_id}.md"
        if rel_path in files:
            raise OkfExportError(f"duplicate export path: {rel_path}")
        files[rel_path] = render_concept(frontmatter, "\n".join(body_lines).strip())
        files[snapshot_path] = snapshot_content
    return dict(sorted(files.items()))


def export_playbooks() -> dict[str, str]:
    """Export built-in investigation playbooks as shared OKF concepts."""
    h = hashlib.sha256()
    for k in sorted(_PLAYBOOKS):
        e = _PLAYBOOKS[k]
        h.update(f"{k}\0{e['title']}\0{e['vertical']}\0{e['fragment']}".encode("utf-8"))
    revision = h.hexdigest()[:16]
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
        record_uri = f"playbooks/builtin#{playbook_id}"
        snapshot_path, snapshot_content, snapshot_hash = _source_snapshot(record_uri, record)
        frontmatter = {
            "type": "Investigation Playbook",
            "title": title,
            "description": f"{title} ({vertical})",
            "tags": ["playbook", vertical],
            "source_uri": record_uri,
            "source_content_hash": snapshot_hash,
            "approved_revision": revision,
            **_STAGING_GOVERNANCE,
        }
        rel_path = f"playbooks/{playbook_id}.md"
        files[rel_path] = render_concept(frontmatter, fragment)
        files[snapshot_path] = snapshot_content
    return dict(sorted(files.items()))


def _luhn_valid(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _contains_ip_address(value: str) -> bool:
    for match in _IP_VALUE.finditer(value):
        try:
            ipaddress.ip_address(match.group(0))
        except ValueError:
            continue
        return True
    return False


def _contains_compact_domestic_phone(value: str) -> bool:
    for match in _COMPACT_DOMESTIC_PHONE_VALUE.finditer(value):
        digits = match.group(0)
        national = digits[1:] if len(digits) == 11 else digits
        if len(national) != 10:
            continue
        return True
    return False


def _contains_likely_person_name(value: str) -> bool:
    words = [
        match.group(0).casefold() for match in re.finditer(r"\b[A-Za-z][A-Za-z'-]{1,29}\b", value)
    ]
    return any(words[index] in _COMMON_GIVEN_NAMES for index in range(len(words)))


def _pii_kind(value: str) -> str | None:
    for kind, pattern in (
        ("email", _EMAIL_VALUE),
        ("phone", _PHONE_VALUE),
        ("phone", _DOMESTIC_PHONE_VALUE),
        ("phone", _INTERNATIONAL_PHONE_VALUE),
        ("account", _ACCOUNT_VALUE),
        ("account", _IBAN_VALUE),
        ("national_id", _SSN_VALUE),
        ("national_id", _NATIONAL_ID_VALUE),
        ("street_address", _STREET_ADDRESS_VALUE),
        ("person_name", _PERSON_NAME_VALUE),
    ):
        if pattern.search(value):
            return kind
    if _contains_compact_domestic_phone(value):
        return "phone"
    if _contains_likely_person_name(value):
        return "person_name"
    if _contains_ip_address(value):
        return "ip_address"
    if any(_luhn_valid(match.group(0)) for match in _CARD_VALUE.finditer(value)):
        return "payment_card"
    return None


def _iter_text_values(value: Any, path: str):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            yield from _iter_text_values(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in sorted(value.items(), key=lambda row: str(row[0])):
            yield from _iter_text_values(item, f"{path}.{key}")


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
    if not _CASE_ID.fullmatch(case_id):
        raise LandmarkCaseSanitizationError(
            "case_id must be a safe opaque identifier using letters, digits, dot, underscore, or hyphen"
        )
    for key, raw_value in case.items():
        if key == "source_content_hash":
            continue
        for value_path, value in _iter_text_values(raw_value, key):
            pii_kind = _pii_kind(value)
            if pii_kind:
                raise LandmarkCaseSanitizationError(
                    f"landmark case contains unsanitized PII ({pii_kind}) in {value_path}"
                )
    source_hash = str(case.get("source_content_hash") or "").strip().lower()
    if len(source_hash) != 64 or not all(c in "0123456789abcdef" for c in source_hash):
        raise LandmarkCaseSanitizationError("source_content_hash must be SHA-256 hex")

    typology_ids = case.get("typology_ids") or []
    rule_ids = case.get("rule_ids") or []
    evidence_ids = case.get("evidence_ids") or []
    for _id_key, _id_val in (("typology_ids", typology_ids), ("rule_ids", rule_ids), ("evidence_ids", evidence_ids)):
        if _id_val and not isinstance(_id_val, list | tuple):
            raise LandmarkCaseSanitizationError(f"{_id_key} must be a list")
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


def export_landmark_case_bundle(
    case: dict[str, Any],
    *,
    tenant_id: str,
) -> dict[str, str]:
    """Export a landmark concept with canonical snapshot and source manifest."""
    if not isinstance(case, dict):
        raise LandmarkCaseSanitizationError("landmark case must be an object")
    tenant = str(tenant_id).strip()
    if not _CASE_ID.fullmatch(tenant):
        raise LandmarkCaseSanitizationError("tenant_id must be a safe opaque identifier")

    candidate = dict(case)
    candidate["source_content_hash"] = "0" * 64
    export_landmark_case(candidate, tenant_id=tenant)

    record: dict[str, Any] = {}
    for key in sorted(set(case) - {"source_content_hash"}):
        raw = case[key]
        if key in {"typology_ids", "rule_ids", "evidence_ids"}:
            if not isinstance(raw, list | tuple):
                raise LandmarkCaseSanitizationError(f"{key} must be a list")
            record[key] = sorted({str(item).strip() for item in raw if str(item).strip()})
        elif isinstance(raw, str):
            record[key] = raw.strip()
        else:
            record[key] = raw

    case_id = str(record["case_id"])
    source_uri = f"landmark-cases/{case_id}"
    snapshot_path, snapshot_content, source_hash = _source_snapshot(source_uri, record)
    concept_path = f"landmark-cases/{case_id}.md"
    concept = export_landmark_case(
        {**record, "source_content_hash": source_hash},
        tenant_id=tenant,
    )
    files = {
        concept_path: concept,
        snapshot_path: snapshot_content,
    }
    files[_SOURCE_MANIFEST_NAME] = render_source_manifest(files)
    return files


def assert_staging_output_path(output: Path, *, repo_root: Path) -> None:
    """Refuse writes to active shared or tenant OKF roots."""
    output_resolved = output.resolve()
    configured: list[Path] = []
    for env_name, default in (
        ("OKF_SHARED_ROOT", repo_root / "knowledge" / "shared"),
        ("OKF_TENANT_ROOT", repo_root / "knowledge" / "tenants"),
    ):
        raw = os.environ.get(env_name, "").strip()
        active = Path(raw).expanduser() if raw else default
        if not active.is_absolute():
            active = repo_root / active
        configured.append(active.resolve())
    shared_active, tenant_active = configured
    for active in (shared_active, tenant_active):
        if (
            output_resolved == active
            or active in output_resolved.parents
            or output_resolved in active.parents
        ):
            raise StagingPathError(f"refusing to export to active OKF root: {active.as_posix()}")


def write_staging_bundle(staging_root: Path, files: dict[str, str], *, repo_root: Path) -> None:
    """Atomically replace a staging bundle so obsolete files cannot survive."""
    assert_staging_output_path(staging_root, repo_root=repo_root)
    staging_root = staging_root.resolve()
    staging_root.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(
        tempfile.mkdtemp(
            prefix=f".{staging_root.name}.candidate-",
            dir=staging_root.parent,
        )
    ).resolve()
    backup = staging_root.parent / (
        f".{staging_root.name}.previous-{os.getpid()}-{uuid.uuid4().hex}"
    )
    try:
        for rel_path, content in sorted(files.items()):
            rel = Path(rel_path)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError(f"invalid relative export path: {rel_path}")
            target = (temp_root / rel).resolve()
            if temp_root not in target.parents and target != temp_root:
                raise ValueError(f"export path escapes staging root: {rel_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            normalized = content.replace("\r\n", "\n").replace("\r", "\n")
            if not normalized.endswith("\n"):
                normalized += "\n"
            target.write_text(normalized, encoding="utf-8", newline="\n")

        if backup.exists():
            shutil.rmtree(backup)
        if staging_root.exists():
            os.replace(staging_root, backup)
        try:
            os.replace(temp_root, staging_root)
        except Exception:
            if backup.exists() and not staging_root.exists():
                os.replace(backup, staging_root)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)


def shared_bundle_index_md() -> str:
    return (
        "---\n"
        'okf_version: "0.1"\n'
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
        chunks.append(export_typologies(typologies, "rules/typology_definitions_v1.json"))

    if include_playbooks:
        chunks.append(export_playbooks())

    concepts = merge_export_files(*chunks)
    return merge_export_files(
        concepts,
        {_SOURCE_MANIFEST_NAME: render_source_manifest(concepts)},
    )
