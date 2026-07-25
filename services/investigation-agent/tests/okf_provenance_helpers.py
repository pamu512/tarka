from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

_MANIFEST_SCHEMA = "tarka.okf_source_manifest/v1"
_SNAPSHOT_SCHEMA = "tarka.okf_source_snapshot/v1"
_SNAPSHOT_ROOT = Path("_provenance") / "sources"


def _snapshot_bytes(source_uri: str, source_record: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            {
                "schema_id": _SNAPSHOT_SCHEMA,
                "source_uri": source_uri,
                "record": source_record,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode()


def attach_concept_provenance(
    root: Path,
    concept_path: Path,
    *,
    source_record: dict[str, Any] | None = None,
) -> str:
    raw = concept_path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) != 3:
        raise ValueError(f"{concept_path}: frontmatter missing")
    meta = yaml.safe_load(parts[1])
    if not isinstance(meta, dict):
        raise ValueError(f"{concept_path}: frontmatter invalid")
    source_uri = str(meta.get("source_uri") or "").strip()
    concept_id = concept_path.relative_to(root).with_suffix("").as_posix()
    record = source_record or {
        "fixture_concept_id": concept_id,
        "fixture_source_marker": str(meta.get("source_content_hash") or ""),
    }
    snapshot = _snapshot_bytes(source_uri, record)
    source_hash = hashlib.sha256(snapshot).hexdigest()
    snapshot_rel = _SNAPSHOT_ROOT / f"{source_hash}.json"
    snapshot_path = root / snapshot_rel
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_bytes(snapshot)

    meta["source_content_hash"] = source_hash
    concept_path.write_text(
        "---\n"
        + yaml.safe_dump(meta, sort_keys=True, allow_unicode=True).strip()
        + "\n---"
        + parts[2],
        encoding="utf-8",
    )

    manifest_path = root / "source-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"schema_id": _MANIFEST_SCHEMA, "sources": {}}
    sources = manifest.setdefault("sources", {})
    prior = sources.get(source_uri)
    entry = {
        "snapshot_path": snapshot_rel.as_posix(),
        "source_content_hash": source_hash,
    }
    if prior is not None and prior != entry:
        raise ValueError(f"duplicate fixture source URI with divergent snapshots: {source_uri}")
    sources[source_uri] = entry
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return source_hash


def rebuild_bundle_provenance(root: Path) -> None:
    shutil.rmtree(root / "_provenance", ignore_errors=True)
    (root / "source-manifest.json").unlink(missing_ok=True)
    for concept_path in sorted(root.rglob("*.md")):
        if concept_path.name in {"index.md", "log.md"}:
            continue
        attach_concept_provenance(root, concept_path)


def remove_concept_provenance(root: Path, source_uri: str) -> None:
    manifest_path = root / "source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["sources"].pop(source_uri)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    snapshot_path = root / str(entry["snapshot_path"])
    if not any(
        row.get("snapshot_path") == entry["snapshot_path"]
        for row in manifest["sources"].values()
        if isinstance(row, dict)
    ):
        snapshot_path.unlink(missing_ok=True)
