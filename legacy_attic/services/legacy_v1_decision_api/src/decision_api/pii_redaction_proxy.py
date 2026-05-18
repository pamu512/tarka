"""Auditor-facing PII redaction for manifest-shaped / evaluate payloads (regex-based)."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

# IPv4 (bounded); IPv6 handled separately.
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
# Loose email (unicode-friendly local part excluded — ASCII-focused for fraud stacks).
_EMAIL_RE = re.compile(
    r"\b([A-Za-z0-9._%+-]{1,256})@([A-Za-z0-9.-]+\.[A-Za-z]{2,63})\b"
)
# Simple IPv6 (compressed forms not exhaustive — extend if needed).
_IPV6_RE = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
    r"|\b(?:[0-9a-fA-F]{1,4}:){1,7}:\b"
    r"|\b(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b"
)

# Keys that typically carry PII even when value shape is ambiguous.
_SENSITIVE_KEY_HINT = re.compile(
    r"(?i)(^|_)(email|e_mail|mail|ip|ip_address|client_ip|remote_addr|"
    r"full_?name|first_?name|last_?name|display_?name|user_?name|"
    r"phone|mobile|ssn|national_?id)(_|$)"
)


def _mask_edges(value: str, *, mask_char: str = "*") -> str:
    """Preserve first and last character; mask the interior (minimum length 3 for effect)."""
    s = value.strip()
    if len(s) <= 2:
        return mask_char * len(s) if s else s
    if len(s) == 3:
        return s[0] + mask_char + s[2]
    return s[0] + (mask_char * (len(s) - 2)) + s[-1]


def mask_email_like(value: str) -> str:
    """Example: ``alice@tarka.com`` → ``a***@tarka.com`` (first local char + domain preserved)."""

    def _sub(m: re.Match[str]) -> str:
        local, domain = m.group(1), m.group(2)
        if not local:
            return m.group(0)
        head = local[0]
        return f"{head}***@{domain}"

    return _EMAIL_RE.sub(_sub, value)


def mask_ipv4_literal(ip: str) -> str:
    """Preserve first and last character of the dotted representation."""
    return _mask_edges(ip)


def mask_ipv6_literal(ip: str) -> str:
    return _mask_edges(ip)


def redact_scalar_string(value: str) -> str:
    """Apply email + IP passes, then edge masking for residual human-readable tokens."""
    if not value:
        return value
    out = value
    out = mask_email_like(out)

    def _v4(m: re.Match[str]) -> str:
        return mask_ipv4_literal(m.group(0))

    out = _IPV4_RE.sub(_v4, out)

    def _v6(m: re.Match[str]) -> str:
        return mask_ipv6_literal(m.group(0))

    out = _IPV6_RE.sub(_v6, out)

    # Long free-text: soften interior while keeping edges (names, addresses).
    if len(out) > 12 and "@" not in out and not _IPV4_RE.search(out):
        parts = out.split()
        if len(parts) >= 2 and all(len(p) >= 2 for p in parts[:2]):
            # Likely "First Last" style token run — mask each word's interior.
            return " ".join(
                _mask_edges(p) if len(p) > 2 else mask_email_like(p) for p in parts
            )
    return out


def redact_by_key_hint(key: str, value: str) -> str:
    """Use field name hints after detecting embedded emails / IPs in the value."""
    v = str(value)
    if _EMAIL_RE.search(v):
        return mask_email_like(v)
    if _IPV4_RE.search(v):
        return _IPV4_RE.sub(lambda m: mask_ipv4_literal(m.group(0)), v)
    if _IPV6_RE.search(v):
        return _IPV6_RE.sub(lambda m: mask_ipv6_literal(m.group(0)), v)
    k = str(key)
    if _SENSITIVE_KEY_HINT.search(k):
        return _mask_edges(v) if len(v) > 2 else "*" * len(v)
    return redact_scalar_string(v)


def redact_flat_payload_entries(entries: dict[str, Any]) -> dict[str, dict[str, str]]:
    """
    Build protobuf-style ``SignalValue`` JSON (string_value branch only) per key.

    Used as an ``input_map.entries``-compatible projection for auditors.
    """
    out: dict[str, dict[str, str]] = {}
    for k, raw in entries.items():
        key = str(k)
        if raw is None:
            continue
        if isinstance(raw, (dict, list)):
            s = json.dumps(raw, separators=(",", ":"), default=str)
            s = redact_by_key_hint(key, s)
        else:
            s = redact_by_key_hint(key, str(raw))
        out[key] = {"string_value": s}
    return out


def deep_redact_mapping(obj: Any, *, key_path: str = "") -> Any:
    """Deep-copy and redact string leaves; dict keys inform masking."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            kp = f"{key_path}.{k}" if key_path else str(k)
            if isinstance(v, str):
                out[k] = redact_by_key_hint(str(k), v)
            else:
                out[k] = deep_redact_mapping(v, key_path=kp)
        return out
    if isinstance(obj, list):
        return [deep_redact_mapping(x, key_path=key_path) for x in obj]
    return obj


def flatten_payload_to_entry_strings(payload: dict[str, Any]) -> dict[str, str]:
    """Flatten nested evaluate payload into dotted keys suitable for ``input_map.entries``."""

    out: dict[str, str] = {}

    def walk(d: dict[str, Any], prefix: str) -> None:
        for k, v in d.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                walk(v, path)
            elif isinstance(v, (list, tuple)):
                out[path] = json.dumps(v, separators=(",", ":"), default=str)
            elif v is None:
                continue
            else:
                out[path] = str(v)

    walk(payload, "")
    return out


def evidence_manifest_json_redact_input_map(manifest: dict[str, Any]) -> dict[str, Any]:
    """
    Given a ``MessageToDict``-style EvidenceManifest (proto field names), redact ``input_map``.

    Expected shape: ``{"input_map": {"entries": {"k": {"string_value": "..." , ...}}}}``.
    """
    m = copy.deepcopy(manifest)
    im = m.get("input_map")
    if not isinstance(im, dict):
        return m
    ent = im.get("entries")
    if not isinstance(ent, dict):
        return m
    new_entries: dict[str, Any] = {}
    for sig_key, sig_val in ent.items():
        if not isinstance(sig_val, dict):
            continue
        branch = {kk: vv for kk, vv in sig_val.items() if vv is not None}
        # Proto JSON uses snake_case values: string_value, bool_value, etc.
        nv: dict[str, Any] = {}
        for fk, fv in branch.items():
            if fk == "string_value" and isinstance(fv, str):
                nv[fk] = redact_by_key_hint(str(sig_key), fv)
            elif isinstance(fv, str):
                nv[fk] = redact_by_key_hint(str(sig_key), fv)
            else:
                nv[fk] = fv
        new_entries[str(sig_key)] = nv
    im["entries"] = new_entries
    m["input_map"] = im
    return m


def is_superuser(auth_user: Any) -> bool:
    """Treat RBAC ``admin`` as superuser for PII policy (see ROLE_HIERARCHY in auth_rbac)."""
    if auth_user is None:
        return False
    if hasattr(auth_user, "has_role"):
        return bool(auth_user.has_role("admin"))
    return False
