"""Scan compiler-style YAML rule sets and map signals ↔ rules (impact analysis)."""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Mirrors crates/tarka-core/src/compiler/yaml.rs MAX_RULE_TREE_DEPTH.
_MAX_EXPR_DEPTH = 96


@dataclass(frozen=True)
class RuleSignalBinding:
    """One YAML rule's dependency on signal names (compiler ``CompareSignal`` leaves)."""

    rule_id: str
    source_file: str
    signals: tuple[str, ...]


@dataclass
class FileScanOutcome:
    """Per-file parse outcome (failures are isolated so the rest of the tree still scans)."""

    relative_path: str
    rules: list[RuleSignalBinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class LineageScanResult:
    """Full crawl result for API serialization."""

    generated_at: str
    rules_root: str
    rules: list[dict[str, Any]]
    impact_by_signal: dict[str, dict[str, Any]]
    files_scanned: list[dict[str, Any]]
    scan_summary: dict[str, Any]


def _should_skip_path(
    path: Path, *, rules_root: Path, excluded_globs: tuple[str, ...]
) -> bool | str:
    """Return skip reason string if path should be skipped, else False."""
    try:
        rel = path.relative_to(rules_root)
    except ValueError:
        return "outside_rules_root"
    parts = rel.parts
    if any(p == "disabled" for p in parts):
        return "under_disabled_segment"
    name = path.name
    if name.startswith(("_", ".")):
        return "underscore_or_dot_prefix"
    rel_posix = rel.as_posix()
    for pattern in excluded_globs:
        if fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(name, pattern):
            return f"excluded_by_glob:{pattern}"
    return False


def _signals_from_expression(
    expr: Any,
    *,
    rule_id: str,
    source_file: str,
    errors: list[str],
    path: str,
    depth: int,
) -> list[str]:
    """Walk one rule expression; extract ``signal_name`` from ``kind: compare_signal`` leaves."""
    if depth > _MAX_EXPR_DEPTH:
        errors.append(
            f"{source_file} rule {rule_id!r}: expression exceeds max depth {_MAX_EXPR_DEPTH} at {path}"
        )
        return []
    if not isinstance(expr, dict):
        errors.append(
            f"{source_file} rule {rule_id!r}: expected mapping at {path}, got {type(expr).__name__}"
        )
        return []

    kind = str(expr.get("kind", "")).strip().lower()
    if kind == "compare_signal":
        raw = expr.get("signal_name")
        if not isinstance(raw, str) or not raw.strip():
            errors.append(
                f"{source_file} rule {rule_id!r}: compare_signal missing non-empty signal_name at {path}"
            )
            return []
        return [raw.strip()]

    if kind == "and" or kind == "or":
        children = expr.get("children")
        if not isinstance(children, list):
            errors.append(
                f"{source_file} rule {rule_id!r}: {kind} requires list children at {path}"
            )
            return []
        out: list[str] = []
        for i, ch in enumerate(children):
            out.extend(
                _signals_from_expression(
                    ch,
                    rule_id=rule_id,
                    source_file=source_file,
                    errors=errors,
                    path=f"{path}.children[{i}]",
                    depth=depth + 1,
                )
            )
        return out

    if kind == "not":
        child = expr.get("child")
        return _signals_from_expression(
            child,
            rule_id=rule_id,
            source_file=source_file,
            errors=errors,
            path=f"{path}.child",
            depth=depth + 1,
        )

    errors.append(f"{source_file} rule {rule_id!r}: unknown expression kind {kind!r} at {path}")
    return []


def _parse_yaml_rule_document(
    doc: Any,
    *,
    source_file: str,
    errors: list[str],
) -> list[RuleSignalBinding]:
    """Parse top-level ``version`` + ``rules[]`` compiler YAML."""
    if not isinstance(doc, dict):
        errors.append(f"{source_file}: document root must be a mapping")
        return []

    rules_raw = doc.get("rules")
    if rules_raw is None:
        errors.append(f"{source_file}: missing top-level 'rules' array")
        return []
    if not isinstance(rules_raw, list):
        errors.append(f"{source_file}: 'rules' must be a list")
        return []

    seen_ids: set[str] = set()
    bindings: list[RuleSignalBinding] = []

    for idx, rule_obj in enumerate(rules_raw):
        if not isinstance(rule_obj, dict):
            errors.append(f"{source_file}: rules[{idx}] must be a mapping")
            continue
        rid = rule_obj.get("id")
        if not isinstance(rid, str) or not rid.strip():
            errors.append(f"{source_file}: rules[{idx}] missing non-empty id")
            continue
        rid_clean = rid.strip()
        if rid_clean in seen_ids:
            errors.append(f"{source_file}: duplicate rule id {rid_clean!r}")
            continue
        seen_ids.add(rid_clean)

        expr = rule_obj.get("expression")
        sigs = _signals_from_expression(
            expr,
            rule_id=rid_clean,
            source_file=source_file,
            errors=errors,
            path=f"rules[{idx}].expression",
            depth=1,
        )
        uniq = tuple(sorted({s for s in sigs}))
        bindings.append(RuleSignalBinding(rule_id=rid_clean, source_file=source_file, signals=uniq))

    return bindings


def _load_yaml_documents(raw: str, *, source_file: str, errors: list[str]) -> list[Any]:
    """Load one or more YAML documents; use first successfully parsed mapping if multi-doc."""
    try:
        docs = list(yaml.safe_load_all(raw))
    except yaml.YAMLError as exc:
        errors.append(f"{source_file}: YAML parse error: {exc}")
        return []

    out: list[Any] = []
    for i, doc in enumerate(docs):
        if doc is None:
            continue
        out.append(doc)
    if not out:
        errors.append(f"{source_file}: empty YAML stream")
    return out


def scan_yaml_rules_tree(
    rules_root: Path,
    *,
    excluded_globs: tuple[str, ...] = (),
    max_files: int = 10_000,
    max_file_bytes: int = 2_000_000,
) -> LineageScanResult:
    """Walk ``rules_root`` for ``*.yaml`` / ``*.yml``, parse compiler rule sets, aggregate lineage."""
    root = rules_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"rules root is not a directory: {root}")

    files_outcomes: list[FileScanOutcome] = []
    files_seen = 0
    truncated = False

    yaml_suffixes = {".yaml", ".yml"}
    stop_walking = False
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        if stop_walking:
            break
        for fname in sorted(filenames):
            path = Path(dirpath) / fname
            if path.suffix.lower() not in yaml_suffixes:
                continue

            skip = _should_skip_path(path, rules_root=root, excluded_globs=excluded_globs)
            if skip:
                logger.debug("skip %s (%s)", path, skip)
                continue

            files_seen += 1
            if files_seen > max_files:
                truncated = True
                stop_walking = True
                break

            rel = path.relative_to(root).as_posix()
            outcome = FileScanOutcome(relative_path=rel)

            try:
                st = path.stat()
                if st.st_size > max_file_bytes:
                    outcome.errors.append(
                        f"file exceeds max_file_bytes ({max_file_bytes}): size={st.st_size}"
                    )
                    files_outcomes.append(outcome)
                    continue

                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                outcome.errors.append(f"read failed: {exc}")
                files_outcomes.append(outcome)
                continue

            docs = _load_yaml_documents(raw, source_file=rel, errors=outcome.errors)
            all_bindings: list[RuleSignalBinding] = []
            for doc in docs:
                if isinstance(doc, dict) and "rules" in doc:
                    all_bindings.extend(
                        _parse_yaml_rule_document(doc, source_file=rel, errors=outcome.errors)
                    )
                else:
                    outcome.errors.append(
                        f"{rel}: skipped YAML document without top-level 'rules' (compiler format)"
                    )

            outcome.rules.extend(all_bindings)
            files_outcomes.append(outcome)

        if truncated:
            break

    rules_payload: list[dict[str, Any]] = []
    impact: dict[str, dict[str, Any]] = {}

    for fo in files_outcomes:
        for b in fo.rules:
            entry = {
                "rule_id": b.rule_id,
                "source_file": b.source_file,
                "signals": list(b.signals),
                "signal_count": len(b.signals),
            }
            rules_payload.append(entry)
            for sig in b.signals:
                bucket = impact.setdefault(
                    sig,
                    {"signal": sig, "rule_refs": []},
                )
                ref = {"rule_id": b.rule_id, "source_file": b.source_file}
                bucket["rule_refs"].append(ref)

    files_json = []
    for fo in files_outcomes:
        fe = list(fo.errors)
        files_json.append(
            {
                "path": fo.relative_path,
                "rules_extracted": len(fo.rules),
                "errors": fe,
                "ok": len(fe) == 0,
            }
        )

    scan_summary = {
        "file_count": len(files_json),
        "rule_bindings": len(rules_payload),
        "signal_count": len(impact),
        "truncated_by_max_files": truncated,
        "max_files": max_files,
        "max_file_bytes": max_file_bytes,
    }

    return LineageScanResult(
        generated_at=datetime.now(timezone.utc).isoformat(),
        rules_root=str(root),
        rules=sorted(rules_payload, key=lambda r: (r["source_file"], r["rule_id"])),
        impact_by_signal=dict(sorted(impact.items(), key=lambda kv: kv[0])),
        files_scanned=files_json,
        scan_summary=scan_summary,
    )


def filter_impact_for_signal(
    full: LineageScanResult,
    signal: str,
) -> dict[str, Any]:
    """Return rules referencing ``signal`` plus minimal metadata."""
    key = signal.strip()
    hit = full.impact_by_signal.get(key)
    if hit is None:
        return {
            "signal": key,
            "matched": False,
            "rules": [],
            "message": "Signal not referenced by any scanned YAML rule.",
        }
    return {
        "signal": key,
        "matched": True,
        "rules": hit["rule_refs"],
        "rule_count": len(hit["rule_refs"]),
    }
