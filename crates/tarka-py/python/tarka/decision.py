"""High-level API: wraps Rust `DecisionInner` with lazy protobuf decode.

`rule_json` must deserialize to a Tarka `RuleExpr` (tagged union), for example::

    {
      "kind": "compare_leaf",
      "id": "check_x",
      "path": "/x",
      "op": "eq",
      "expected": 1
    }

Rules are **content-addressed**: ``rule_content_id_hex`` must equal the SHA-256 (hex) of the exact
UTF-8 bytes of ``rule_json``. Use :func:`rule_content_id` to compute it for a string you control.

Ingress backpressure (Rust ``governor`` token bucket + bounded concurrency) may raise
:class:`BackpressureSignal` when admission is denied (HTTP APIs should map this to ``429 Too Many Requests``).
"""

from __future__ import annotations

import json
from typing import Any, Optional

_decision_inner_type = Any


def _trace_ids_from_propagated_current_context() -> tuple[Optional[str], Optional[str]]:
    """Materialize the active OpenTelemetry context using :func:`opentelemetry.propagate.inject`.

    The global text map propagator writes a W3C ``traceparent`` value into ``carrier``; we parse
    ``trace-id`` and ``parent-id`` (32 + 16 hex) for the Rust bridge. Returns ``(None, None)`` when
    the carrier has no usable ``traceparent`` or identifiers are invalid / all-zero.
    """
    from opentelemetry.propagate import inject

    carrier: dict[str, str] = {}
    inject(carrier)
    traceparent: Optional[str] = None
    for key, value in carrier.items():
        if key.lower() == "traceparent" and isinstance(value, str) and value.strip():
            traceparent = value.strip()
            break
    if not traceparent:
        return (None, None)
    parts = traceparent.split("-")
    if len(parts) != 4:
        return (None, None)
    _version, trace_id_hex, parent_id_hex, _flags = parts
    if len(trace_id_hex) != 32 or len(parent_id_hex) != 16:
        return (None, None)
    hex_digits = frozenset("0123456789abcdefABCDEF")
    if not all(c in hex_digits for c in trace_id_hex) or not all(
        c in hex_digits for c in parent_id_hex
    ):
        return (None, None)
    try:
        if int(trace_id_hex, 16) == 0 or int(parent_id_hex, 16) == 0:
            return (None, None)
    except ValueError:
        return (None, None)
    return (trace_id_hex.lower(), parent_id_hex.lower())


def _effective_trace_ids_for_evaluate(
    trace_id: Optional[str],
    span_id: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Resolve ``(trace_id, span_id)`` for :func:`evaluate`.

    When ``trace_id`` is ``None`` or empty/whitespace-only, identifiers are taken from the current
    OTel context via :func:`_trace_ids_from_propagated_current_context` (``span_id`` is ignored in
    that branch). Otherwise the stripped ``trace_id`` is used with the ``span_id`` argument unchanged.
    """
    if trace_id is None:
        return _trace_ids_from_propagated_current_context()
    stripped = trace_id.strip()
    if not stripped:
        return _trace_ids_from_propagated_current_context()
    return (stripped, span_id)


def rule_content_id(rule_json: str) -> str:
    """Lowercase hex SHA-256 of ``rule_json`` encoded as UTF-8 (the immutable rule address)."""
    from tarka import _tarka

    return _tarka.rule_content_id(rule_json)


def rule_expr_mermaid_flowchart(rule_json: str) -> str:
    """Return a Mermaid ``flowchart TD`` document for a ``RuleExpr`` JSON tree (analyst visualization)."""
    from tarka import _tarka

    return _tarka.rule_expr_mermaid_flowchart(rule_json)


def ingest_stats() -> dict[str, Any]:
    """Return ingestion gate counters and configuration keys (environment-driven).

    Includes ``capacity``, ``in_flight``, ``token_refill_per_sec``, ``buffer_pressure_percent`` (80),
    and the names of environment variables used for tuning.
    """
    from tarka import _tarka

    return _tarka.ingest_stats()


def backpressure_payload(exc: BaseException) -> dict[str, Any] | None:
    """If ``exc`` is :class:`BackpressureSignal`, decode the JSON payload from ``args[0]``.

    Returns a dict with ``kind`` (``rate_limited`` or ``buffer_pressure``), ``retry_after_ms``,
    and ``reason_codes`` when parsing succeeds; otherwise ``None``.
    """
    from tarka import _tarka

    if type(exc) is not _tarka.BackpressureSignal:
        return None
    if not exc.args:
        return None
    raw = exc.args[0]
    if not isinstance(raw, str):
        return None
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


class TarkaDecision:
    """FastAPI-friendly wrapper: protobuf bytes stay untouched until `.manifest` is read."""

    __slots__ = ("_inner", "_manifest")

    def __init__(self, inner: _decision_inner_type) -> None:
        self._inner = inner
        self._manifest: Optional[Any] = None

    @property
    def decision(self) -> bool:
        return self._inner.decision

    @property
    def is_partial(self) -> bool:
        return self._inner.is_partial

    @property
    def partial_error(self) -> Optional[str]:
        return self._inner.partial_error

    @property
    def failing_rule_id(self) -> Optional[str]:
        return self._inner.failing_rule_id

    def manifest_proto_bytes(self) -> bytes:
        """Raw `EvidenceManifest` protobuf (copy-free view via PyBytes on CPython)."""
        return bytes(self._inner.manifest_proto_bytes())

    @property
    def manifest(self):
        """Lazily decode wire protobuf — safe to skip when handlers only forward bytes."""
        if self._manifest is None:
            from tarka.models import decode_wire_manifest

            self._manifest = decode_wire_manifest(self.manifest_proto_bytes())
        return self._manifest

    @property
    def has_merkle_proof(self) -> bool:
        from tarka.verifier import manifest_has_merkle_proof_field

        return manifest_has_merkle_proof_field(self.manifest)

    def merkle_proof_proto_bytes(self) -> Optional[bytes]:
        from tarka.verifier import manifest_has_merkle_proof_field

        if not manifest_has_merkle_proof_field(self.manifest):
            return None
        return bytes(self._inner.merkle_proof_proto_bytes())

    def merkle_signature_bytes(self) -> Optional[bytes]:
        b = self._inner.merkle_signature_bytes()
        return None if b is None else bytes(b)


def evaluate(
    rule_json: str,
    data_json: str,
    rule_content_id_hex: str,
    *,
    fast_path: bool = True,
    engine_version: str = "tarka-core",
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    replay_wall_time_ns: Optional[int] = None,
    mock_redis=None,
    mock_lists=None,
    mock_custom=None,
) -> TarkaDecision:
    """Evaluate rules; returns protobuf bytes without JSON overhead.

    Parameters
    ----------
    rule_content_id_hex
        64-character hex encoding of SHA-256(rule_json UTF-8 bytes). Must match exactly or the
        engine raises :class:`tarka.verifier.ManifestIntegrityError` with
        ``failure_reason=CANONICALIZATION_ERROR`` (Rust ``SecurityIntegrityViolation``).
    fast_path
        When ``True`` (default), Merkle tree construction and Ed25519 signing are **skipped**
        entirely on the Rust side for maximum throughput.
    trace_id
        When set to a non-blank string, used as the W3C trace id for evidence correlation; ``span_id``
        is passed through for Rust parent linking when both are valid. When ``None`` or blank after
        stripping, the trace id and parent span id are read from the **current** OpenTelemetry context:
        the wrapper calls :func:`opentelemetry.propagate.inject` and parses the resulting
        ``traceparent`` value (so the global propagator stack must include W3C Trace Context, as with
        default OTel instrumentation).
    span_id
        Optional W3C **parent** span id (16 hex) used only when ``trace_id`` resolves to an explicit
        non-blank string. When context propagation supplies the trace id (``trace_id`` is ``None`` or
        blank), the parent id comes from that same propagated context and this parameter is ignored.
    replay_wall_time_ns
        When set, nanoseconds since Unix epoch used as the evaluation wall clock (replay / audit).
        Omits real ``SystemTime::now()`` so time-dependent rules (weekends, cut-offs) reproduce.

    Raises
    ------
    BackpressureSignal
        When the ingestion gate denies admission (token bucket or buffer pressure above the
        configured high-water mark). Map to HTTP 429 in APIs — see :func:`backpressure_payload`.
    """
    from tarka import _tarka

    eff_tid, eff_sid = _effective_trace_ids_for_evaluate(trace_id, span_id)
    inner = _tarka.evaluate(
        rule_json,
        data_json,
        rule_content_id_hex,
        fast_path,
        engine_version,
        eff_tid,
        eff_sid,
        replay_wall_time_ns,
        mock_redis,
        mock_lists,
        mock_custom,
    )
    return TarkaDecision(inner)
