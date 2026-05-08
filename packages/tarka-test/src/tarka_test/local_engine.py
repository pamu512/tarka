"""Optional local ``tarka.evaluate`` manifest verification (same protobuf EvidenceManifest as production rules)."""

from __future__ import annotations

import json
from typing import Any, Mapping


def evaluate_manifest_steps_local(
    *,
    rule_json: str,
    rule_content_id_hex: str,
    data_obj: Mapping[str, Any],
    fast_path: bool,
) -> list[dict[str, Any]]:
    """Run in-process evaluation and return EvidenceManifest trace steps as dicts."""
    from tarka_test.manifest_match import extract_manifest_steps

    try:
        from tarka import _tarka  # type: ignore[import-untyped]
        from tarka.evidence.wire.v1.evidence_pb2 import EvidenceManifest  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError(
            "Local manifest verification requires the `tarka` package "
            "(install optional extra: pip install 'tarka-test[tarka]')."
        ) from e

    data_json = json.dumps(data_obj, separators=(",", ":"), sort_keys=True)
    inner = _tarka.evaluate(
        rule_json,
        data_json,
        rule_content_id_hex,
        fast_path,
        "tarka-core",
        None,
        None,
        None,
        None,
        None,
        None,
    )
    raw = inner.manifest_proto_bytes()
    msg = EvidenceManifest()
    msg.ParseFromString(bytes(raw))
    return extract_manifest_steps(msg)


def build_default_data_obj(case: Mapping[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten payload + input_signals into a JSON object suitable for ``evaluate()``."""
    out: dict[str, Any] = {}
    payload = body.get("payload")
    if isinstance(payload, Mapping):
        out.update(dict(payload))
    sigs = case.get("input_signals")
    if isinstance(sigs, Mapping):
        out.update(dict(sigs))
    dc = body.get("device_context")
    if isinstance(dc, Mapping):
        s = dc.get("signals")
        if isinstance(s, Mapping):
            for k, v in s.items():
                out.setdefault(k, v)
    return out
