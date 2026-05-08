#!/usr/bin/env python3
"""End-to-end stack verification: Decision API evaluate → trace correlation → ClickHouse manifest row →
wire ``ManifestVerifier`` integrity (same semantics as ``tarka_core`` / Rust audit CLI ``verify``).

This script does **not** ship raw protobuf in the default ClickHouse schema (only ``raw_manifest_sha256``).
Wire bytes are resolved in order:

1. If ``evidence_manifests.raw_manifest`` exists and is non-empty for the matched row, use it (optional column).
2. Otherwise set ``VERIFY_STACK_MANIFEST_PATH`` to a local ``.pb`` file; the script checks
   ``SHA256(file) == raw_manifest_sha256`` from ClickHouse before verifying.

Prerequisites
-------------
* Running decision API (e.g. ``VERIFY_STACK_DECISION_API``, default core-api ``/decisions`` mount).
* OpenTelemetry exporting traces; ClickHouse ``otel_spans`` populated for the synthetic ``traceparent``.
* Evidence manifests ingested into ``evidence_manifests`` with ``trace_json`` steps carrying
  ``otel_trace_id`` matching the W3C trace id (32 hex).
* ``TARKA_VERIFYING_KEY`` — hex-encoded 32-byte Ed25519 **public** key used to verify the sealed manifest.
* Python env with ``tarka`` installed (``ManifestVerifier``).

Environment
-------------
* ``VERIFY_STACK_DECISION_API`` — base URL for decisions (default ``http://127.0.0.1:8000/decisions``).
* ``VERIFY_STACK_MANIFEST_PATH`` — optional path to wire manifest bytes when CH has no ``raw_manifest`` column.
* ``TARKA_VERIFYING_KEY`` — required.

Exit codes
----------
``0`` only when API + (optional) Rust audit + OTel + CH row + wire integrity verification succeed.
Non-zero otherwise.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _validate_sql_ident(name: str, ctx: str) -> None:
    if name and all(c.isascii() and (c.isalnum() or c == "_") for c in name):
        return
    raise ValueError(f"invalid SQL identifier for {ctx}: {name!r}")


def _clickhouse_post(
    *,
    base_url: str,
    database: str,
    user: str,
    password: str,
    query: str,
    timeout: float,
    row_policy_tenant_id: str | None = None,
) -> str:
    _validate_sql_ident(database, "database")
    base = base_url.rstrip("/") + "/"
    qdb = quote(database, safe="")
    extra = ""
    if row_policy_tenant_id:
        extra = f"&tarka_tenant_id={quote(row_policy_tenant_id, safe='')}"
    url = f"{base}?database={qdb}{extra}"
    req = urllib.request.Request(
        url,
        data=query.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    if user or password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _otel_span_count(
    *,
    clickhouse_url: str,
    database: str,
    otel_table: str,
    user: str,
    password: str,
    trace_id_hex: str,
    timeout: float,
    row_policy_tenant_id: str | None,
) -> int:
    _validate_sql_ident(database, "database")
    _validate_sql_ident(otel_table, "otel_table")
    tid = trace_id_hex.lower().replace("-", "")
    if len(tid) != 32 or any(c not in "0123456789abcdef" for c in tid):
        raise ValueError("trace_id_hex must be 32 lowercase hex chars")
    q = (
        f"SELECT count() AS c FROM `{database}`.`{otel_table}` "
        f"WHERE TraceId = '{tid}' FORMAT JSONEachRow"
    )
    body = _clickhouse_post(
        base_url=clickhouse_url,
        database=database,
        user=user,
        password=password,
        query=q,
        timeout=timeout,
        row_policy_tenant_id=row_policy_tenant_id,
    )
    line = next((ln for ln in body.splitlines() if ln.strip()), "")
    if not line:
        return 0
    row = json.loads(line)
    return int(row.get("c", 0))


def _ch_column_exists(
    *,
    clickhouse_url: str,
    database: str,
    table: str,
    column: str,
    user: str,
    password: str,
    timeout: float,
    row_policy_tenant_id: str | None,
) -> bool:
    _validate_sql_ident(database, "database")
    _validate_sql_ident(table, "table")
    _validate_sql_ident(column, "column")
    q = (
        f"SELECT count() AS c FROM system.columns "
        f"WHERE database = '{database}' AND table = '{table}' AND name = '{column}' "
        f"FORMAT JSONEachRow"
    )
    body = _clickhouse_post(
        base_url=clickhouse_url,
        database=database,
        user=user,
        password=password,
        query=q,
        timeout=timeout,
        row_policy_tenant_id=row_policy_tenant_id,
    )
    line = next((ln for ln in body.splitlines() if ln.strip()), "")
    if not line:
        return False
    return int(json.loads(line).get("c", 0)) > 0


def _escape_sql_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _fetch_manifest_row_for_trace(
    *,
    clickhouse_url: str,
    database: str,
    evidence_table: str,
    user: str,
    password: str,
    w3c_trace_id_hex: str,
    timeout: float,
    row_policy_tenant_id: str | None,
    include_raw_manifest_hex: bool,
) -> dict[str, Any] | None:
    """Same correlation predicate as ``crates/tarka-audit-cli/src/ch.rs`` (otel_trace_id in trace_json)."""
    _validate_sql_ident(database, "database")
    _validate_sql_ident(evidence_table, "evidence_table")
    tid_esc = _escape_sql_string(w3c_trace_id_hex.lower().replace("-", ""))
    raw_sel = (
        "ifNull(hex(raw_manifest), '') AS raw_manifest_hex"
        if include_raw_manifest_hex
        else "'' AS raw_manifest_hex"
    )
    q = (
        f"SELECT "
        f"tenant_id, manifest_id, engine_version, timestamp_ns, final_decision, total_execution_time_us, "
        f"signals, trace_json, crypto_algorithm, crypto_signature_hex, crypto_key_id, "
        f"hex(raw_manifest_sha256) AS raw_manifest_sha256_hex, {raw_sel} "
        f"FROM `{database}`.`{evidence_table}` "
        f"WHERE arrayExists( "
        f"  obj -> lower(replaceAll(JSONExtractString(obj, 'otel_trace_id'), '-', '')) = '{tid_esc}', "
        f"  JSONExtractArrayRaw(toJSONString(trace_json)) "
        f") "
        f"ORDER BY timestamp_ns DESC "
        f"LIMIT 1 "
        f"FORMAT JSONEachRow"
    )
    body = _clickhouse_post(
        base_url=clickhouse_url,
        database=database,
        user=user,
        password=password,
        query=q,
        timeout=timeout,
        row_policy_tenant_id=row_policy_tenant_id,
    )
    line = next((ln for ln in body.splitlines() if ln.strip()), "")
    if not line:
        return None
    return json.loads(line)


def _normalize_sha256_digest(val: Any) -> bytes | None:
    if val is None:
        return None
    if isinstance(val, (bytes, memoryview, bytearray)):
        b = bytes(val)
        return b if len(b) == 32 else None
    if isinstance(val, str):
        s = val.strip().lower()
        if len(s) == 64 and all(c in "0123456789abcdef" for c in s):
            try:
                return bytes.fromhex(s)
            except ValueError:
                return None
    return None


def _decode_verifying_key_hex(raw: str) -> bytes:
    s = raw.strip()
    if s.startswith(("0x", "0X")):
        s = s[2:]
    if len(s) != 64 or any(c not in "0123456789abcdefABCDEF" for c in s):
        raise ValueError("TARKA_VERIFYING_KEY must be 64 hex chars (32-byte Ed25519 public key)")
    return binascii.unhexlify(s)


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"detail": raw[:2000]}
        return e.code, body if isinstance(body, dict) else {"detail": body}


def _get_json(url: str, *, headers: dict[str, str], timeout: float) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, json.loads(raw) if raw else {}


def _sha256_file(path: Path) -> bytes:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.digest()


def _resolve_wire_manifest_input(
    *,
    ch_row: dict[str, Any],
    manifest_path: str | None,
) -> bytes | Path:
    """Return in-memory wire bytes, or a path to verify via ``verify_manifest_integrity_from_file``."""
    hex_raw = (ch_row.get("raw_manifest_hex") or "").strip()
    if hex_raw:
        try:
            wire = bytes.fromhex(hex_raw)
        except ValueError as exc:
            raise RuntimeError(f"ClickHouse raw_manifest hex decode failed: {exc}") from exc
        if wire:
            return wire

    path_raw = (manifest_path or os.environ.get("VERIFY_STACK_MANIFEST_PATH") or "").strip()
    if not path_raw:
        raise RuntimeError(
            "No wire manifest bytes available: add nullable binary column "
            "`raw_manifest` to evidence_manifests (preferred), or set VERIFY_STACK_MANIFEST_PATH "
            "to the on-disk wire EvidenceManifest `.pb` whose SHA-256 matches "
            "`raw_manifest_sha256` in ClickHouse."
        )

    p = Path(path_raw).expanduser()
    if not p.is_file():
        raise RuntimeError(f"VERIFY_STACK_MANIFEST_PATH is not a file: {p}")

    digest = _sha256_file(p)
    expected = _normalize_sha256_digest(ch_row.get("raw_manifest_sha256_hex"))
    if expected is None:
        raise RuntimeError("ClickHouse row missing raw_manifest_sha256_hex; cannot validate file binding")
    if digest != expected:
        raise RuntimeError(
            "manifest file SHA-256 does not match ClickHouse raw_manifest_sha256 "
            f"(file={digest.hex()} ch={expected.hex()})"
        )
    return p


def main() -> int:
    p = argparse.ArgumentParser(
        description="Verify stack: API evaluate → ClickHouse manifest → ManifestVerifier wire integrity."
    )
    p.add_argument(
        "--decision-api",
        default=os.environ.get("VERIFY_STACK_DECISION_API", "http://127.0.0.1:8000/decisions"),
        help="Decision API base URL",
    )
    p.add_argument(
        "--tenant-id",
        default=os.environ.get("VERIFY_STACK_TENANT_ID", "verify-stack"),
    )
    p.add_argument(
        "--entity-id",
        default=os.environ.get("VERIFY_STACK_ENTITY_ID", "verify-stack-entity"),
    )
    p.add_argument(
        "--api-key",
        default=(os.environ.get("VERIFY_STACK_API_KEY") or os.environ.get("DEMO_API_KEY") or "").strip()
        or None,
    )
    p.add_argument(
        "--clickhouse-url",
        default=os.environ.get("CLICKHOUSE_HTTP_URL", "http://127.0.0.1:8123"),
    )
    p.add_argument(
        "--clickhouse-database",
        default=os.environ.get("CLICKHOUSE_DATABASE", "tarka_audit"),
    )
    p.add_argument(
        "--otel-spans-table",
        default=os.environ.get("CLICKHOUSE_OTEL_SPANS_TABLE", "otel_spans"),
    )
    p.add_argument(
        "--evidence-table",
        default=os.environ.get("CLICKHOUSE_TABLE", "evidence_manifests"),
    )
    p.add_argument("--clickhouse-user", default=os.environ.get("CLICKHOUSE_USER", "default"))
    p.add_argument("--clickhouse-password", default=os.environ.get("CLICKHOUSE_PASSWORD", ""))
    p.add_argument(
        "--row-policy-tenant-id",
        default=os.environ.get("CLICKHOUSE_ROW_POLICY_TENANT_ID", "").strip() or None,
    )
    p.add_argument(
        "--manifest-path",
        default=None,
        help="Wire manifest `.pb` file (overrides VERIFY_STACK_MANIFEST_PATH)",
    )
    p.add_argument("--http-timeout", type=float, default=45.0)
    p.add_argument("--ch-timeout", type=float, default=30.0)
    p.add_argument(
        "--max-wait",
        type=float,
        default=float(os.environ.get("VERIFY_STACK_MAX_WAIT_SECS", "180")),
        help="Seconds to poll ClickHouse for manifest ingest",
    )
    p.add_argument("--poll-interval", type=float, default=3.0)
    p.add_argument(
        "--allow-python-json-engine",
        action="store_true",
        help="Do not require json_rule_engine.engine == 'rust' in audit snapshot",
    )
    p.add_argument(
        "--skip-rust-audit",
        action="store_true",
        help="Skip GET /v1/audit/{trace_id} Rust engine snapshot check",
    )
    args = p.parse_args()

    vkey = (os.environ.get("TARKA_VERIFYING_KEY") or "").strip()
    if not vkey:
        print(
            "[verify_stack] FAIL: TARKA_VERIFYING_KEY is not set (Ed25519 verifying key hex).",
            file=sys.stderr,
        )
        return 2
    try:
        pubkey = _decode_verifying_key_hex(vkey)
    except ValueError as exc:
        print(f"[verify_stack] FAIL: {exc}", file=sys.stderr)
        return 2

    try:
        from tarka.verifier import ManifestVerifier
    except ImportError as exc:
        print(
            "[verify_stack] FAIL: cannot import tarka.verifier (install the `tarka` package). "
            f"Detail: {exc}",
            file=sys.stderr,
        )
        return 2

    w3c_trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    traceparent = f"00-{w3c_trace_id}-{span_id}-01"

    base = args.decision_api.rstrip("/")
    eval_url = f"{base}/v1/decisions/evaluate"

    headers: dict[str, str] = {"traceparent": traceparent}
    if args.api_key:
        headers["x-api-key"] = args.api_key

    payload = {
        "tenant_id": args.tenant_id,
        "entity_id": args.entity_id,
        "event_type": "payment",
        "payload": {"verify_stack": True, "amount": 1.0, "currency": "USD"},
    }

    status, body = _post_json(eval_url, payload, headers=headers, timeout=args.http_timeout)
    if status != 200 or not isinstance(body, dict):
        print(f"[stage-1-api] FAIL: HTTP {status} body={body!r}", file=sys.stderr)
        return 1
    api_tid = body.get("trace_id")
    if not api_tid:
        print("[stage-1-api] FAIL: missing trace_id in response", file=sys.stderr)
        return 1
    print(f"[stage-1-api] OK: decision={body.get('decision')} trace_id={api_tid}")

    if not args.skip_rust_audit:
        audit_url = f"{base}/v1/audit/{api_tid}?tenant_id={quote(args.tenant_id)}"
        audit: Any = None
        for attempt in range(30):
            try:
                _, audit = _get_json(audit_url, headers=headers, timeout=args.http_timeout)
                break
            except urllib.error.HTTPError as e:
                if e.code == 404 and attempt < 29:
                    time.sleep(1.0)
                    continue
                print(f"[stage-2-rust-engine] FAIL: audit HTTP {e.code}", file=sys.stderr)
                return 1
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                print(f"[stage-2-rust-engine] FAIL: {e}", file=sys.stderr)
                return 1

        if not isinstance(audit, dict):
            print("[stage-2-rust-engine] FAIL: audit response not JSON object", file=sys.stderr)
            return 1

        jre = audit.get("json_rule_engine")
        if not isinstance(jre, dict):
            print(
                "[stage-2-rust-engine] FAIL: audit payload has no json_rule_engine",
                file=sys.stderr,
            )
            return 1
        engine = str(jre.get("engine") or "").lower()
        if not args.allow_python_json_engine and engine != "rust":
            print(
                f"[stage-2-rust-engine] FAIL: expected engine 'rust', got {engine!r} "
                "(use --allow-python-json-engine to waive).",
                file=sys.stderr,
            )
            return 1
        if jre.get("fallback_active") is True:
            print("[stage-2-rust-engine] FAIL: fallback_active is True", file=sys.stderr)
            return 1
        print(f"[stage-2-rust-engine] OK: engine={engine!r}")
    else:
        print("[stage-2-rust-engine] SKIP (--skip-rust-audit)")

    has_raw_col = _ch_column_exists(
        clickhouse_url=args.clickhouse_url,
        database=args.clickhouse_database,
        table=args.evidence_table,
        column="raw_manifest",
        user=args.clickhouse_user,
        password=args.clickhouse_password,
        timeout=args.ch_timeout,
        row_policy_tenant_id=args.row_policy_tenant_id,
    )

    deadline = time.monotonic() + args.max_wait
    ch_row: dict[str, Any] | None = None
    last_otel = 0
    while time.monotonic() < deadline:
        last_otel = _otel_span_count(
            clickhouse_url=args.clickhouse_url,
            database=args.clickhouse_database,
            otel_table=args.otel_spans_table,
            user=args.clickhouse_user,
            password=args.clickhouse_password,
            trace_id_hex=w3c_trace_id,
            timeout=args.ch_timeout,
            row_policy_tenant_id=args.row_policy_tenant_id,
        )
        print(f"[stage-3-otel-clickhouse] probe: otel_spans count={last_otel} trace={w3c_trace_id}")

        ch_row = _fetch_manifest_row_for_trace(
            clickhouse_url=args.clickhouse_url,
            database=args.clickhouse_database,
            evidence_table=args.evidence_table,
            user=args.clickhouse_user,
            password=args.clickhouse_password,
            w3c_trace_id_hex=w3c_trace_id,
            timeout=args.ch_timeout,
            row_policy_tenant_id=args.row_policy_tenant_id,
            include_raw_manifest_hex=has_raw_col,
        )
        if ch_row is not None:
            break
        time.sleep(args.poll_interval)

    if last_otel == 0:
        print(
            "[stage-3-otel-clickhouse] FAIL: no spans for W3C trace id (check OTLP export).",
            file=sys.stderr,
        )
        return 1

    if ch_row is None:
        print(
            "[stage-4-clickhouse-manifest] FAIL: no evidence_manifests row for this trace "
            "(trace_json.otel_trace_id correlation).",
            file=sys.stderr,
        )
        return 1

    print(f"[stage-4-clickhouse-manifest] OK: manifest_id={ch_row.get('manifest_id')}")

    try:
        wire_input = _resolve_wire_manifest_input(
            ch_row=ch_row,
            manifest_path=args.manifest_path,
        )
    except RuntimeError as exc:
        print(f"[stage-4b-wire-bytes] FAIL: {exc}", file=sys.stderr)
        return 1

    if isinstance(wire_input, Path):
        result = ManifestVerifier.verify_manifest_integrity_from_file(wire_input, pubkey)
    else:
        result = ManifestVerifier.verify_manifest_integrity(wire_input, pubkey)
    if not result.status:
        reason = result.failure_reason.value if result.failure_reason else "unknown"
        print(f"[stage-5-manifest-integrity] FAIL: {reason}", file=sys.stderr)
        return 1

    print("[stage-5-manifest-integrity] OK: ManifestVerifier wire integrity passed")
    print("PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
