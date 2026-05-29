"""Evidence manifest trace → Mermaid-oriented JSON (ClickHouse-backed)."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.exceptions import DatabaseError
from fastapi import APIRouter, Depends, HTTPException
from google.protobuf.json_format import ParseDict, ParseError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from analytics.queries import validate_sql_identifier

from decision_api.config import settings
from decision_api.deps import get_clickhouse, run_clickhouse_sync

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

log = logging.getLogger("decision-api.manifest_visualize")

router = APIRouter(prefix="/v1/manifest", tags=["manifest"])


def _optional_trace_proto_validate(steps_payload: list[dict[str, Any]]) -> None:
    """When ``viz`` extra (``tarka``) is installed, validate steps against wire ``ExecutionStep`` protos."""
    try:
        from tarka.evidence.wire.v1 import evidence_pb2 as wire_evidence_pb2
    except ImportError:
        return
    try:
        for item in steps_payload:
            step = wire_evidence_pb2.ExecutionStep()
            step_dict = dict(item)
            if "logic_operator" in step_dict and "operator" not in step_dict:
                step_dict["operator"] = step_dict.pop("logic_operator")
            ParseDict(step_dict, step, ignore_unknown_fields=True)
    except ParseError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "MANIFEST_TRACE_PROTO_MISMATCH",
                "message": "trace_json does not match wire ExecutionStep schema.",
                "cause": str(e),
            },
        ) from e


def _decode_snapshot_value(raw: str) -> Any:
    s = raw.strip()
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return raw


def decode_state_snapshot(snap: Any) -> dict[str, Any]:
    """Decode protobuf map<string,string> values (JSON blobs, bools, numerics)."""
    if not isinstance(snap, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in snap.items():
        key = str(k)
        if isinstance(v, str):
            out[key] = _decode_snapshot_value(v)
        elif isinstance(v, (dict, list)):
            out[key] = v
        else:
            out[key] = v
    return out


def _normalize_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return False


def _normalize_step(raw: Any, step_index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "MANIFEST_TRACE_STEP_INVALID",
                "message": f"trace step {step_index} must be an object.",
            },
        )
    rule_id = raw.get("rule_id")
    if rule_id is None or str(rule_id).strip() == "":
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "MANIFEST_TRACE_STEP_INVALID",
                "message": f"trace step {step_index} missing rule_id.",
            },
        )
    operands_raw = raw.get("operands") or []
    if not isinstance(operands_raw, list):
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "MANIFEST_TRACE_STEP_INVALID",
                "message": f"trace step {step_index} operands must be a list.",
            },
        )
    snap_raw = raw.get("state_snapshot") or {}
    if not isinstance(snap_raw, dict):
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "MANIFEST_TRACE_STEP_INVALID",
                "message": f"trace step {step_index} state_snapshot must be an object.",
            },
        )
    snap_str: dict[str, str] = {}
    for sk, sv in snap_raw.items():
        snap_str[str(sk)] = (
            sv if isinstance(sv, str) else json.dumps(sv, sort_keys=True)
        )

    return {
        "rule_id": str(rule_id),
        "logic_operator": str(raw.get("logic_operator") or ""),
        "operands": [str(x) for x in operands_raw],
        "result": _normalize_bool(raw.get("result")),
        "state_snapshot": snap_str,
        "state_snapshot_decoded": decode_state_snapshot(snap_str),
    }


def _parse_trace_json(trace_json: Any) -> list[dict[str, Any]]:
    if trace_json is None:
        return []
    if isinstance(trace_json, str):
        try:
            trace_json = json.loads(trace_json)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason_code": "MANIFEST_TRACE_JSON_INVALID",
                    "message": "trace_json is not valid JSON.",
                    "cause": str(e),
                },
            ) from e
    if not isinstance(trace_json, list):
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "MANIFEST_TRACE_JSON_INVALID",
                "message": "trace_json must be a JSON array of steps.",
            },
        )
    steps: list[dict[str, Any]] = []
    for i, row in enumerate(trace_json):
        steps.append(_normalize_step(row, i))
    proto_payload = [
        {
            "rule_id": s["rule_id"],
            "logic_operator": s["logic_operator"],
            "operands": s["operands"],
            "result": s["result"],
            "state_snapshot": s["state_snapshot"],
        }
        for s in steps
    ]
    _optional_trace_proto_validate(proto_payload)
    return steps


def _mermaid_escape_label(text: str, *, max_len: int = 200) -> str:
    s = text.replace('"', "'").replace("\n", " ").strip()
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def _build_mermaid_structure(steps: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    edge_seq = 0

    for i, st in enumerate(steps):
        nid = f"n{i}"
        label = _mermaid_escape_label(
            f"{st['rule_id']}<br/>{st['logic_operator'] or '-'}<br/>"
            f"{'true' if st['result'] else 'false'}"
        )
        nodes.append(
            {
                "id": nid,
                "step_index": i,
                "rule_id": st["rule_id"],
                "logic_operator": st["logic_operator"],
                "operands": st["operands"],
                "result": st["result"],
                "state_snapshot": st["state_snapshot"],
                "state_snapshot_decoded": st["state_snapshot_decoded"],
                "label_text": label,
            }
        )

    for i in range(len(steps) - 1):
        src = f"n{i}"
        dst = f"n{i + 1}"
        flow = "true" if steps[i]["result"] else "false"
        edges.append(
            {
                "id": f"e{edge_seq}",
                "from": src,
                "to": dst,
                "label": flow,
                "kind": "execution",
                "arrow": "-->",
            }
        )
        edge_seq += 1

    def _prior_step_index_for_rule(cur: int, operand_rule_id: str) -> int | None:
        for j in range(cur - 1, -1, -1):
            if steps[j]["rule_id"] == operand_rule_id:
                return j
        return None

    for i, st in enumerate(steps):
        op = (st["logic_operator"] or "").strip()
        for operand_id in st["operands"]:
            j = _prior_step_index_for_rule(i, operand_id)
            if j is None:
                continue
            src = f"n{j}"
            dst = f"n{i}"
            lbl = op if op else "operand"
            edges.append(
                {
                    "id": f"e{edge_seq}",
                    "from": src,
                    "to": dst,
                    "label": _mermaid_escape_label(str(lbl), max_len=64),
                    "kind": "operand_flow",
                    "operator": op,
                    "operand_rule_id": operand_id,
                    "arrow": ".->",
                }
            )
            edge_seq += 1

    lines = ["flowchart TD"]
    for n in nodes:
        lines.append(f'  {n["id"]}["{n["label_text"]}"]')
    for e in edges:
        esc = _mermaid_escape_label(str(e["label"]), max_len=80)
        arrow = e.get("arrow", "-->")
        if arrow == ".->":
            lines.append(f"  {e['from']} -.->|{esc}| {e['to']}")
        else:
            lines.append(f"  {e['from']} -->|{esc}| {e['to']}")

    return {
        "version": 1,
        "direction": "TD",
        "diagram": "\n".join(lines),
        "nodes": nodes,
        "edges": edges,
    }


def _qualified_manifest_table() -> str:
    db = validate_sql_identifier(settings.clickhouse_database.strip())
    tbl = validate_sql_identifier(settings.clickhouse_evidence_manifests_table.strip())
    return f"`{db}`.`{tbl}`"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=0.08, max=1.2),
    retry=retry_if_exception_type((DatabaseError, TimeoutError, OSError)),
    reraise=True,
)
def _manifest_query_settings() -> dict[str, str] | None:
    tid = (settings.clickhouse_row_policy_tenant_id or "").strip()
    if not tid:
        return None
    return {"tarka_tenant_id": tid}


def _query_manifest_row_sync(
    client: Client, sql: str, parameters: dict[str, Any]
) -> Any:
    qs = _manifest_query_settings()
    if qs is not None:
        return client.query(sql, parameters=parameters, settings=qs)
    return client.query(sql, parameters=parameters)


async def _fetch_manifest_bundle(ch: Client, manifest_id: uuid.UUID) -> dict[str, Any]:
    table_ref = _qualified_manifest_table()
    sql = (
        f"SELECT trace_json, signals, engine_version, timestamp_ns, "
        f"final_decision, total_execution_time_us "
        f"FROM {table_ref} "
        f"WHERE manifest_id = toUUID({{mid:String}}) "
        f"LIMIT 1"
    )
    params = {"mid": str(manifest_id)}

    def _run():
        return _query_manifest_row_sync(ch, sql, params)

    try:
        result = await run_clickhouse_sync(ch, _run)
    except DatabaseError as e:
        log.warning("ClickHouse manifest fetch failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "MANIFEST_CLICKHOUSE_ERROR",
                "message": "Could not load manifest from ClickHouse.",
                "cause": str(e),
            },
        ) from e
    except OSError as e:
        log.warning("ClickHouse manifest fetch I/O error: %s", e)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "MANIFEST_CLICKHOUSE_IO",
                "message": "ClickHouse I/O failure while loading manifest.",
                "cause": str(e),
            },
        ) from e
    except TimeoutError as e:
        log.warning("ClickHouse manifest fetch timed out: %s", e)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "MANIFEST_CLICKHOUSE_TIMEOUT",
                "message": "ClickHouse query exceeded client timeout.",
                "cause": str(e),
            },
        ) from e

    rows = result.result_rows or ()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={
                "reason_code": "MANIFEST_NOT_FOUND",
                "message": "No evidence manifest with this id.",
            },
        )
    row = rows[0]
    cols = tuple(str(c) for c in (result.column_names or ()))
    if len(row) < 6 or len(cols) < 6:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "MANIFEST_CLICKHOUSE_SHAPE",
                "message": "Unexpected ClickHouse response shape for manifest row.",
            },
        )
    return {
        "trace_json": row[0],
        "signals": row[1],
        "engine_version": row[2],
        "timestamp_ns": row[3],
        "final_decision": row[4],
        "total_execution_time_us": row[5],
    }


@router.get("/{manifest_id}/visualize")
async def visualize_manifest(
    manifest_id: uuid.UUID,
    ch: Client = Depends(get_clickhouse),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Return execution-path graph (rules as nodes, boolean / operand edges) for Mermaid.js."""
    bundle = await _fetch_manifest_bundle(ch, manifest_id)
    steps = _parse_trace_json(bundle["trace_json"])
    mermaid = _build_mermaid_structure(steps)

    signals = bundle["signals"]
    if not isinstance(signals, dict):
        signals = {}

    final_u8 = bundle["final_decision"]
    final_bool = (
        bool(int(final_u8))
        if isinstance(final_u8, (int, float))
        else _normalize_bool(final_u8)
    )

    return {
        "manifest_id": str(manifest_id),
        "mermaid_js": mermaid,
        "execution_path": [
            {
                "step_index": n["step_index"],
                "rule_id": n["rule_id"],
                "logic_operator": n["logic_operator"],
                "operands": n["operands"],
                "result": n["result"],
                "state_snapshot": n["state_snapshot"],
                "state_snapshot_decoded": n["state_snapshot_decoded"],
            }
            for n in mermaid["nodes"]
        ],
        "metadata": {
            "engine_version": bundle["engine_version"],
            "timestamp_ns": bundle["timestamp_ns"],
            "final_decision": final_bool,
            "total_execution_time_us": bundle["total_execution_time_us"],
            "signals": signals,
        },
    }
