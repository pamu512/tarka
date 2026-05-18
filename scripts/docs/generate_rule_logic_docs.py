#!/usr/bin/env python3
"""Scan compiler-style YAML rule sets and generate MkDocs markdown for self-documenting logic.

Each discovered rule gets:
  * human-readable logic (derived from ``kind: and|or|not|compare_signal`` trees),
  * sorted signal dependency list (``compare_signal`` leaves),
  * benchmark link from an optional JSON manifest (per-rule URL or team default).

The output is intended to be committed or produced in CI immediately before ``mkdocs build``.

Dependencies: PyYAML (see ``docs/requirements.txt``).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

logger = logging.getLogger("generate_rule_logic_docs")

# Mirrors ``signal_lineage._MAX_EXPR_DEPTH``.
_MAX_EXPR_DEPTH = 96
_MAX_FILE_BYTES_DEFAULT = 2_000_000
_MAX_FILES_DEFAULT = 10_000

_DEFAULT_BENCH_URL = (
    "https://github.com/tarka/tarka/blob/main/"
    ".github/workflows/tarka-core-benchmark-regression.yml"
)
_DEFAULT_BENCH_LABEL = "tarka-core Criterion regression (CI workflow)"


@dataclass
class ScannedRule:
    """Rule extracted from one file (paths relative to that rules root only)."""

    rule_id: str
    source_within_root: str
    rule_version: int | None
    signals: tuple[str, ...]
    logic_line: str
    yaml_source_excerpt: str


@dataclass
class RuleRecord:
    """One YAML rule row for documentation (paths relative to repository root)."""

    rule_id: str
    source_relpath: str
    anchor_id: str
    rule_version: int | None
    signals: tuple[str, ...]
    logic_line: str
    yaml_source_excerpt: str


@dataclass
class FileScanResult:
    relative_path: str
    rules: list[ScannedRule] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")


def _should_skip_path(path: Path, *, rules_root: Path, excluded_globs: tuple[str, ...]) -> str | None:
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
    return None


def _looks_like_compiler_rule_set(doc: dict[str, Any]) -> bool:
    if not isinstance(doc.get("version"), int):
        return False
    rules = doc.get("rules")
    if not isinstance(rules, list):
        return False
    if not rules:
        return True
    first = rules[0]
    return isinstance(first, dict) and isinstance(first.get("expression"), dict)


def _signals_from_expression(
    expr: Any,
    *,
    rule_id: str,
    source_file: str,
    errors: list[str],
    path: str,
    depth: int,
) -> list[str]:
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
                f"{source_file} rule {rule_id!r}: compare_signal missing signal_name at {path}"
            )
            return []
        return [raw.strip()]

    if kind in ("and", "or"):
        children = expr.get("children")
        if not isinstance(children, list):
            errors.append(f"{source_file} rule {rule_id!r}: {kind} requires list children at {path}")
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


def _fmt_expected(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _expression_to_logic(expr: Any) -> str:
    if not isinstance(expr, dict):
        return "?"
    kind = str(expr.get("kind", "")).strip().lower()
    if kind == "compare_signal":
        sn = expr.get("signal_name", "?")
        op = expr.get("op", "?")
        return f"{sn} {op} {_fmt_expected(expr.get('expected'))}"
    if kind == "and":
        children = expr.get("children")
        if not isinstance(children, list) or not children:
            return "(empty AND)"
        parts = [_expression_to_logic(ch) for ch in children]
        joined = " AND ".join(parts)
        return f"({joined})" if len(parts) > 1 else parts[0]
    if kind == "or":
        children = expr.get("children")
        if not isinstance(children, list) or not children:
            return "(empty OR)"
        parts = [_expression_to_logic(ch) for ch in children]
        joined = " OR ".join(parts)
        return f"({joined})" if len(parts) > 1 else parts[0]
    if kind == "not":
        inner = _expression_to_logic(expr.get("child"))
        return f"NOT ({inner})"
    return f"<{kind or 'unknown'}>"


def _dump_rule_yaml_snippet(rule_obj: dict[str, Any]) -> str:
    try:
        return yaml.safe_dump(
            rule_obj,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ).rstrip()
    except yaml.YAMLError as e:
        return f"# (yaml dump failed: {e})"


def _parse_compiler_documents(
    raw: str,
    *,
    source_file: str,
    errors: list[str],
) -> list[dict[str, Any]]:
    try:
        docs = list(yaml.safe_load_all(raw))
    except yaml.YAMLError as exc:
        errors.append(f"{source_file}: YAML parse error: {exc}")
        return []
    out: list[dict[str, Any]] = []
    for doc in docs:
        if doc is None:
            continue
        if not isinstance(doc, dict):
            errors.append(f"{source_file}: skipped non-mapping document")
            continue
        if not _looks_like_compiler_rule_set(doc):
            logger.debug("skip non-compiler document in %s", source_file)
            continue
        out.append(doc)
    return out


def _parse_rules_in_document(
    doc: dict[str, Any],
    *,
    source_file: str,
    errors: list[str],
) -> list[ScannedRule]:
    rules_raw = doc.get("rules")
    assert isinstance(rules_raw, list)
    ver = doc.get("version")
    rule_version = int(ver) if isinstance(ver, int) else None

    seen: set[str] = set()
    records: list[ScannedRule] = []

    for idx, rule_obj in enumerate(rules_raw):
        if not isinstance(rule_obj, dict):
            errors.append(f"{source_file}: rules[{idx}] must be a mapping")
            continue
        rid = rule_obj.get("id")
        if not isinstance(rid, str) or not rid.strip():
            errors.append(f"{source_file}: rules[{idx}] missing non-empty id")
            continue
        rid_clean = rid.strip()
        if rid_clean in seen:
            errors.append(f"{source_file}: duplicate rule id {rid_clean!r}")
            continue
        seen.add(rid_clean)

        expr = rule_obj.get("expression")
        if not isinstance(expr, dict):
            errors.append(f"{source_file}: rule {rid_clean!r} missing expression mapping")
            continue

        sigs = _signals_from_expression(
            expr,
            rule_id=rid_clean,
            source_file=source_file,
            errors=errors,
            path=f"rules[{idx}].expression",
            depth=1,
        )
        uniq = tuple(sorted({s for s in sigs}))
        logic = _expression_to_logic(expr)
        snippet = _dump_rule_yaml_snippet(rule_obj)
        records.append(
            ScannedRule(
                rule_id=rid_clean,
                source_within_root=source_file,
                rule_version=rule_version,
                signals=uniq,
                logic_line=logic,
                yaml_source_excerpt=snippet,
            )
        )

    return records


def _walk_yaml_rule_files(
    rules_root: Path,
    *,
    excluded_globs: tuple[str, ...],
    max_files: int,
    max_file_bytes: int,
) -> tuple[list[FileScanResult], bool]:
    root = rules_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"rules root is not a directory: {root}")

    outcomes: list[FileScanResult] = []
    files_seen = 0
    truncated = False
    yaml_suffixes = {".yaml", ".yml"}

    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for fname in sorted(filenames):
            path = Path(dirpath) / fname
            if path.suffix.lower() not in yaml_suffixes:
                continue

            skip = _should_skip_path(path, rules_root=root, excluded_globs=excluded_globs)
            if skip:
                outcomes.append(
                    FileScanResult(
                        relative_path=path.relative_to(root).as_posix(),
                        skipped=True,
                        skip_reason=skip,
                    )
                )
                continue

            files_seen += 1
            if files_seen > max_files:
                truncated = True
                break

            rel = path.relative_to(root).as_posix()
            fr = FileScanResult(relative_path=rel)

            try:
                st = path.stat()
                if st.st_size > max_file_bytes:
                    fr.errors.append(
                        f"file exceeds max_file_bytes ({max_file_bytes}): size={st.st_size}"
                    )
                    outcomes.append(fr)
                    continue
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                fr.errors.append(f"read failed: {exc}")
                outcomes.append(fr)
                continue

            for doc in _parse_compiler_documents(raw, source_file=rel, errors=fr.errors):
                fr.rules.extend(
                    _parse_rules_in_document(
                        doc,
                        source_file=rel,
                        errors=fr.errors,
                    )
                )
            outcomes.append(fr)

        if truncated:
            break

    return outcomes, truncated


def _load_benchmark_manifest(path: Path | None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "default_url": _DEFAULT_BENCH_URL,
        "default_label": _DEFAULT_BENCH_LABEL,
        "per_rule": {},
    }
    if path is None:
        return base
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"benchmark manifest read failed: {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"benchmark manifest invalid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("benchmark manifest root must be an object")
    per = data.get("per_rule")
    if per is not None and not isinstance(per, dict):
        raise RuntimeError("benchmark manifest 'per_rule' must be an object")
    du = data.get("default_url")
    dl = data.get("default_label")
    if du is not None:
        if not isinstance(du, str) or not du.strip():
            raise RuntimeError("default_url must be a non-empty string when set")
        base["default_url"] = du.strip()
    if dl is not None:
        if not isinstance(dl, str) or not dl.strip():
            raise RuntimeError("default_label must be a non-empty string when set")
        base["default_label"] = dl.strip()
    if isinstance(per, dict):
        cleaned: dict[str, str] = {}
        for k, v in per.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise RuntimeError("per_rule keys and values must be strings")
            cleaned[k.strip()] = v.strip()
        base["per_rule"] = cleaned
    return base


def _bench_cell(rule_id: str, manifest: dict[str, Any]) -> str:
    per: dict[str, str] = manifest["per_rule"]
    url = per.get(rule_id) or str(manifest["default_url"])
    label = "Rule-specific benchmark" if rule_id in per else str(manifest["default_label"])
    return f"[{label}]({url})"


def _stable_anchor_id(rule_id: str, source_relpath: str, rules_root: Path, repo_root: Path) -> str:
    abs_src = (rules_root / source_relpath).resolve()
    try:
        rel = abs_src.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        rel = abs_src.as_posix()
    digest = hashlib.sha256(f"{rule_id}\0{rel}".encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", rule_id.strip())[:40].strip("_").lower() or "rule"
    return f"{safe}-{digest}"


def _collect_all_rules(
    roots: Iterable[Path],
    *,
    repo_root: Path,
    excluded_globs: tuple[str, ...],
    max_files: int,
    max_file_bytes: int,
) -> tuple[list[RuleRecord], list[FileScanResult], bool]:
    all_rules: list[RuleRecord] = []
    all_files: list[FileScanResult] = []
    truncated_any = False
    for root in roots:
        if not root.is_dir():
            logger.warning("skip missing rules root: %s", root)
            continue
        files, truncated = _walk_yaml_rule_files(
            root,
            excluded_globs=excluded_globs,
            max_files=max_files,
            max_file_bytes=max_file_bytes,
        )
        truncated_any = truncated_any or truncated
        for fr in files:
            if fr.skipped:
                all_files.append(fr)
                continue
            for r in fr.rules:
                anchor = _stable_anchor_id(r.rule_id, r.source_within_root, root, repo_root)
                try:
                    src_display = (root / r.source_within_root).resolve().relative_to(
                        repo_root.resolve()
                    ).as_posix()
                except ValueError:
                    src_display = (root / r.source_within_root).as_posix()
                all_rules.append(
                    RuleRecord(
                        rule_id=r.rule_id,
                        source_relpath=src_display,
                        anchor_id=anchor,
                        rule_version=r.rule_version,
                        signals=r.signals,
                        logic_line=r.logic_line,
                        yaml_source_excerpt=r.yaml_source_excerpt,
                    )
                )
            all_files.append(fr)
    return all_rules, all_files, truncated_any


def _build_markdown(
    rules: list[RuleRecord],
    *,
    manifest: dict[str, Any],
    generated_note: str,
    scan_roots: list[str],
    truncated: bool,
    file_errors: list[str],
) -> str:
    lines: list[str] = [
        "# YAML rule logic reference",
        "",
        "!!! note \"Generated\"",
        f"    {generated_note}",
        "",
        "This page lists **compiler-style YAML** rules (Rust evaluator schema): boolean expressions over **signals**.",
        "It does not enumerate Decision API JSON packs (`*.json`); see [Rule Authoring](rules.md).",
        "",
        "## Scan roots",
        "",
    ]
    for r in scan_roots:
        lines.append(f"- `{r}`")
    lines.extend(["", "## Summary", ""])
    if truncated:
        lines.append(
            "!!! warning \"Scan truncated\""
            "\n    File walk hit `--max-files`; some YAML files may be missing from this report."
        )
        lines.append("")
    if file_errors:
        lines.append("!!! failure \"Parse or I/O issues\"")
        for e in file_errors[:50]:
            lines.append(f"    - {e}")
        if len(file_errors) > 50:
            lines.append(f"    - … and {len(file_errors) - 50} more")
        lines.append("")

    lines.extend(
        [
            f"- **Rules documented:** {len(rules)}",
            f"- **Unique rule ids:** {len({r.rule_id for r in rules})}",
            "",
            "## Rule index",
            "",
            "| Rule ID | Source | Signals | Logic (summary) | Benchmark | Detail |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )

    for r in rules:
        sigs = ", ".join(f"`{s}`" for s in r.signals) if r.signals else "—"
        logic_esc = r.logic_line.replace("|", "\\|")
        bench = _bench_cell(r.rule_id, manifest)
        detail = f"[Jump](#{r.anchor_id})"
        lines.append(
            f"| `{r.rule_id}` | `{r.source_relpath}` | {sigs} | {logic_esc} | {bench} | {detail} |"
        )

    lines.extend(["", "## Rule details", ""])

    id_counts: dict[str, int] = {}
    for r in rules:
        id_counts[r.rule_id] = id_counts.get(r.rule_id, 0) + 1

    for r in rules:
        title = (
            f"{r.rule_id} (`{r.source_relpath}`)"
            if id_counts[r.rule_id] > 1
            else r.rule_id
        )
        lines.append(f"### {title} {{#{r.anchor_id}}}")
        lines.append("")
        lines.append(f"- **Source:** `{r.source_relpath}`")
        ver = r.rule_version
        lines.append(f"- **Rule set version:** `{ver}`" if ver is not None else "- **Rule set version:** —")
        lines.append(f"- **Signals:** {', '.join(f'`{s}`' for s in r.signals) if r.signals else '—'}")
        lines.append("- **Logic:**")
        lines.append(f"    {r.logic_line}")
        lines.append("")
        bench_url = (manifest["per_rule"].get(r.rule_id) or str(manifest["default_url"])).strip()
        bench_label = (
            "Rule-specific benchmark report"
            if r.rule_id in manifest["per_rule"]
            else str(manifest["default_label"])
        )
        lines.append(f"- **Benchmark ({bench_label}):** [{bench_url}]({bench_url})")
        lines.append("")
        lines.append("#### YAML excerpt")
        lines.append("")
        lines.append("```yaml")
        lines.extend(r.yaml_source_excerpt.splitlines())
        lines.append("```")
        lines.append("")

    lines.append("## Benchmark linking")
    lines.append("")
    lines.append(
        "Per-rule Criterion URLs are optional: the OSS repo publishes **suite-level** "
        "`tarka-core` benches (see workflow above). Copy `docs/benchmark-links.example.json` "
        "to a manifest path your team controls, add `per_rule` URLs (CI artifacts, Grafana, "
        "internal perf dashboards), and pass `--benchmark-manifest` when generating this page."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _gather_file_errors(files: list[FileScanResult]) -> list[str]:
    out: list[str] = []
    for fr in files:
        if fr.skipped:
            continue
        for e in fr.errors:
            out.append(f"{fr.relative_path}: {e}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/docs/generated/logic-reference.md"),
        help="Markdown file to write (MkDocs path under docs_dir).",
    )
    parser.add_argument(
        "--rules-root",
        dest="rules_roots",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory to scan (repeatable). Default: docs/examples/compiler-yaml-rules.",
    )
    parser.add_argument(
        "--exclude-glob",
        dest="exclude_globs",
        action="append",
        default=[],
        metavar="PATTERN",
        help="fnmatch pattern relative to each rules root (repeatable).",
    )
    parser.add_argument("--max-files", type=int, default=_MAX_FILES_DEFAULT)
    parser.add_argument("--max-file-bytes", type=int, default=_MAX_FILE_BYTES_DEFAULT)
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=None,
        help="JSON with default_url, default_label, per_rule {rule_id: url}.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root for default --rules-root resolution.",
    )
    parser.add_argument("--verbose", action="store_true")
    ns = parser.parse_args(argv)
    _configure_logging(ns.verbose)

    roots = ns.rules_roots
    if not roots:
        roots = [
            ns.repo_root / "docs" / "examples" / "compiler-yaml-rules",
            ns.repo_root / "services" / "ml-scoring" / "rules",
        ]

    resolved_roots = [Path(p).expanduser().resolve() for p in roots]
    excluded = tuple(ns.exclude_globs) if ns.exclude_globs else ()

    try:
        manifest = _load_benchmark_manifest(ns.benchmark_manifest)
    except RuntimeError as e:
        logger.error("%s", e)
        return 2

    try:
        rules, files, truncated = _collect_all_rules(
            resolved_roots,
            repo_root=ns.repo_root.resolve(),
            excluded_globs=excluded,
            max_files=ns.max_files,
            max_file_bytes=ns.max_file_bytes,
        )
    except FileNotFoundError as e:
        logger.error("%s", e)
        return 2

    file_errors = _gather_file_errors(files)
    gen_line = (
        f"Generated at **{datetime.now(UTC).isoformat()}** by "
        "`scripts/docs/generate_rule_logic_docs.py` — do not edit by hand."
    )
    repo_base = ns.repo_root.resolve()

    def _try_rel(path: Path) -> str:
        try:
            return path.resolve().relative_to(repo_base).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    scan_labels = [_try_rel(p) for p in resolved_roots]

    md = _build_markdown(
        rules,
        manifest=manifest,
        generated_note=gen_line,
        scan_roots=scan_labels,
        truncated=truncated,
        file_errors=file_errors,
    )

    out_path: Path = ns.output
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
    except OSError as e:
        logger.error("write failed: %s: %s", out_path, e)
        return 2

    logger.info("wrote %s (%d rules)", out_path, len(rules))
    if file_errors:
        logger.warning("%d file-level issue(s) recorded in output", len(file_errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
