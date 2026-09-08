#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

"""Generate Helm values from cloud deployment presets."""
PRESET_DIR = Path("infra/deploy/helm/fraud-stack/presets")
PLACEHOLDER_MAP = {
    "__IMAGE_REGISTRY__": "image_registry",
    "__DB_URL__": "db_url",
    "__REDIS_URL__": "redis_url",
}

# Images that can be sha256-pinned in Helm values. Lite/demo are not in this set.
DIGEST_FIELD_KEYS = ("coreApi", "signalApi", "investigationAgent")
_DIGEST_KEY_ALIASES = {
    "coreapi": "coreApi",
    "signalapi": "signalApi",
    "investigationagent": "investigationAgent",
}
SHA256_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# G2 grade path: mutable tags alone are not enough.
GRADE_PRESETS = frozenset({"prod-on-k8s"})
_TOP_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*):(?:\s|$)")
_ENABLED_RE = re.compile(r"^  enabled:\s*(\S+)")
_DIGEST_LINE_RE = re.compile(r"^  digest:\s*(.*)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate cloud-specific Helm values from a preset."
    )
    parser.add_argument(
        "--preset",
        required=True,
        choices=sorted(p.stem for p in PRESET_DIR.glob("*.yaml")),
        help="Preset name without .yaml",
    )
    parser.add_argument(
        "--image-registry",
        dest="image_registry",
        default="",
        help=("Container registry prefix, e.g. <acct>.dkr.ecr.<region>.amazonaws.com/tarka"),
    )
    parser.add_argument(
        "--db-url",
        dest="db_url",
        default="",
        help="Managed Postgres URL for presets that require it",
    )
    parser.add_argument(
        "--redis-url",
        dest="redis_url",
        default="",
        help="Managed Redis URL for presets that require it",
    )
    parser.add_argument(
        "--digest-map",
        dest="digest_map",
        default="",
        help=(
            "Image digest map for prod-on-k8s (required unless --allow-empty-digest). "
            "key=sha256:<64-hex> lines or a JSON object. Keys: coreApi, signalApi, "
            "investigationAgent (aliases: core-api, signal-api, investigation-agent)."
        ),
    )
    parser.add_argument(
        "--allow-empty-digest",
        action="store_true",
        help=(
            "Permit empty image digests on prod-on-k8s. That is a limitation / "
            "non-grade render (CI helm template of placeholders), not an immutable pin."
        ),
    )
    parser.add_argument(
        "--namespace", default="", help="Optional namespace comment for generated file headers"
    )
    parser.add_argument("--output", required=True, help="Output values file path")
    return parser.parse_args()


def ensure_placeholders_are_resolved(raw: str) -> list[str]:
    unresolved: list[str] = []
    for placeholder in PLACEHOLDER_MAP:
        if placeholder in raw:
            unresolved.append(placeholder)
    return unresolved


def canon_digest_key(raw: str) -> str | None:
    n = raw.strip().lower().replace("_", "").replace("-", "")
    return _DIGEST_KEY_ALIASES.get(n)


def validate_sha256_digest(value: str) -> bool:
    return bool(SHA256_DIGEST_RE.match(value.strip()))


def parse_digest_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"digest-map file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise SystemExit(f"digest-map empty: {path}")
    text = raw.strip()
    items: list[tuple[str, str]]
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"digest-map JSON invalid: {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise SystemExit(f"digest-map JSON must be an object: {path}")
        items = [(str(k), str(v)) for k, v in data.items()]
    else:
        items = []
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "=" in s:
                key, val = s.split("=", 1)
            elif ":" in s:
                key, val = s.split(":", 1)
            else:
                raise SystemExit(f"digest-map line {i}: expected key=sha256:<64-hex>")
            items.append((key.strip(), val.strip().strip("\"'")))
    out: dict[str, str] = {}
    for key_raw, val in items:
        key = canon_digest_key(key_raw)
        if key is None:
            raise SystemExit(
                f"digest-map unknown key {key_raw!r} (use coreApi / signalApi / investigationAgent)"
            )
        if not validate_sha256_digest(val):
            raise SystemExit(
                f"invalid digest for {key}: {val!r} (need sha256:<64-hex>, not a mutable tag)"
            )
        out[key] = val
    return out


def apply_digest_map(rendered: str, digest_map: dict[str, str]) -> str:
    current = ""
    written: set[str] = set()
    out: list[str] = []

    def _flush_digest() -> None:
        if current in digest_map and current not in written:
            out.append(f'  digest: "{digest_map[current]}"')
            written.add(current)

    for line in rendered.splitlines():
        top = _TOP_KEY_RE.match(line)
        if top:
            _flush_digest()
            current = top.group(1)
        if current in digest_map and _DIGEST_LINE_RE.match(line):
            out.append(f'  digest: "{digest_map[current]}"')
            written.add(current)
            continue
        out.append(line)
    _flush_digest()
    return "\n".join(out)


def _section_fields(rendered: str) -> dict[str, dict[str, str]]:
    current = ""
    fields: dict[str, dict[str, str]] = {}
    for line in rendered.splitlines():
        top = _TOP_KEY_RE.match(line)
        if top:
            current = top.group(1)
            fields.setdefault(current, {})
            continue
        if current not in DIGEST_FIELD_KEYS:
            continue
        enabled = _ENABLED_RE.match(line)
        if enabled:
            fields[current]["enabled"] = enabled.group(1).strip().strip("\"'")
            continue
        digest = _DIGEST_LINE_RE.match(line)
        if digest:
            fields[current]["digest"] = digest.group(1).strip().strip("\"'")
    return fields


def enabled_digest_keys(rendered: str) -> tuple[str, ...]:
    fields = _section_fields(rendered)
    keys: list[str] = []
    for key in DIGEST_FIELD_KEYS:
        if key not in fields:
            continue
        info = fields[key]
        enabled = info.get("enabled", "true").lower()
        if enabled == "true":
            keys.append(key)
    return tuple(keys)


def empty_enabled_digests(rendered: str) -> list[str]:
    fields = _section_fields(rendered)
    missing: list[str] = []
    for key in enabled_digest_keys(rendered):
        digest = (fields.get(key) or {}).get("digest", "")
        if not validate_sha256_digest(digest):
            missing.append(key)
    return missing


def main() -> int:
    args = parse_args()

    preset_path = PRESET_DIR / f"{args.preset}.yaml"
    if not preset_path.exists():
        raise SystemExit(f"Preset not found: {preset_path}")

    if args.digest_map and args.allow_empty_digest:
        raise SystemExit("use --digest-map or --allow-empty-digest, not both")

    rendered = preset_path.read_text(encoding="utf-8")
    for placeholder, arg_name in PLACEHOLDER_MAP.items():
        value = getattr(args, arg_name, "")
        if value:
            rendered = rendered.replace(placeholder, value)

    unresolved = ensure_placeholders_are_resolved(rendered)
    if unresolved:
        missing_args = sorted({PLACEHOLDER_MAP[item] for item in unresolved})
        raise SystemExit(
            "Missing required arguments for preset placeholders: "
            + ", ".join(f"--{arg.replace('_', '-')}" for arg in missing_args)
        )

    digest_map: dict[str, str] = {}
    if args.digest_map:
        digest_map = parse_digest_map(Path(args.digest_map))
        rendered = apply_digest_map(rendered, digest_map)

    if args.preset in GRADE_PRESETS and not args.allow_empty_digest:
        if not args.digest_map:
            raise SystemExit(
                "prod-on-k8s requires --digest-map (sha256 pins). "
                "Mutable tags alone are not the grade path. "
                "Pass --allow-empty-digest only for non-grade CI helm template "
                "(empty digest is a limitation, not an immutable claim)."
            )
        missing = empty_enabled_digests(rendered)
        if missing:
            raise SystemExit(
                "prod-on-k8s --digest-map missing sha256 for enabled images: " + ", ".join(missing)
            )

    header = [
        "# Generated by infra/scripts/deploy/generate_cloud_values.py",
        f"# Preset: {args.preset}",
    ]
    if args.namespace:
        header.append(f"# Namespace: {args.namespace}")
    if args.allow_empty_digest:
        header.append("# Digest: empty (limitation / non-grade; not an immutable pin)")
    elif digest_map:
        header.append("# Digest: sha256 pins from --digest-map")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(header) + "\n\n" + rendered + "\n", encoding="utf-8")

    print(f"Generated values file: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
