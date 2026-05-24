"""
Shadow AI **Scout** strategy: DuckDB scan for coordinated hardware bursts (Prompt 194).

Detects when more than ``min_distinct_accounts`` unique ``acc_id`` values share the same
``canvas_hash`` (wire ``ch``) or ``webgl_vendor`` (wire ``wv``) inside a sliding
``window_hours`` interval on ``raw_signals``.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from shadow_agent.schemas import HypothesisReport

logger = logging.getLogger(__name__)

FingerprintKind = Literal["canvas_hash", "webgl_vendor"]

_DEFAULT_DUCK_PATH = "transactions.duckdb"
_DEFAULT_MIN_ACCOUNTS = 6  # strictly > 5 unique acc_ids
_DEFAULT_WINDOW_HOURS = 4
_MAX_ACCOUNT_IDS = 32


def scout_coordinated_burst_mode() -> str:
    """``off`` | ``auto`` (default) | ``always`` — inject scout into Shadow evaluate when enabled."""
    return (os.environ.get("SHADOW_SCOUT_COORDINATED_BURST_MODE") or "auto").strip().lower()


def wants_scout_coordinated_burst(graph_context: dict[str, Any] | None) -> bool:
    mode = scout_coordinated_burst_mode()
    if mode in ("off", "disabled", "false", "0"):
        return False
    if mode == "always":
        return True
    if graph_context and graph_context.get("scout_coordinated_bursts") is not None:
        return False
    return True


def duckdb_path() -> str:
    return (
        os.environ.get("SHADOW_SCOUT_DUCKDB_PATH")
        or os.environ.get("SIGNAL_DUCKDB_PATH")
        or _DEFAULT_DUCK_PATH
    ).strip()


def _min_distinct_accounts() -> int:
    raw = (os.environ.get("SHADOW_SCOUT_BURST_MIN_ACCOUNTS") or "").strip()
    if not raw:
        return _DEFAULT_MIN_ACCOUNTS
    try:
        return max(2, int(raw, 10))
    except ValueError:
        return _DEFAULT_MIN_ACCOUNTS


def _window_hours() -> int:
    raw = (os.environ.get("SHADOW_SCOUT_WINDOW_HOURS") or "").strip()
    if not raw:
        return _DEFAULT_WINDOW_HOURS
    try:
        return max(1, int(raw, 10))
    except ValueError:
        return _DEFAULT_WINDOW_HOURS


def _lookback_hours() -> int:
    raw = (os.environ.get("SHADOW_SCOUT_LOOKBACK_HOURS") or "168").strip()
    try:
        return max(_window_hours(), int(raw, 10))
    except ValueError:
        return 168


def format_burst_narrative(
    *,
    fingerprint_kind: FingerprintKind,
    fingerprint_value: str,
    distinct_account_count: int,
    window_hours: int,
    window_start: datetime,
    window_end: datetime,
) -> str:
    kind_label = "canvas hash" if fingerprint_kind == "canvas_hash" else "WebGL vendor"
    return (
        f"Coordinated burst: {distinct_account_count} distinct accounts shared the same "
        f"{kind_label} ({fingerprint_value!r}) within a {window_hours}-hour window "
        f"({window_start.isoformat()} → {window_end.isoformat()})."
    )


def suggested_shadow_rule(
    *,
    fingerprint_kind: FingerprintKind,
    fingerprint_value: str,
) -> dict[str, Any]:
    field = "canvas_hash" if fingerprint_kind == "canvas_hash" else "webgl_vendor"
    short = fingerprint_value.replace(" ", "")[:12]
    return {
        "id": f"scout_{fingerprint_kind}_{short}",
        "when": [{"op": "eq", "field": field, "value": fingerprint_value}],
        "score_delta": 25.0,
        "metadata": {
            "is_shadow": True,
            "source": "scout_coordinated_burst",
            "fingerprint_kind": fingerprint_kind,
        },
    }


def _backtest_gate_mode() -> str:
    return (os.environ.get("SHADOW_SCOUT_BACKTEST_GATE") or "auto").strip().lower()


def _backtest_gate_enabled() -> bool:
    return _backtest_gate_mode() not in ("off", "disabled", "false", "0")


def _apply_backtest_gate(
    report_dict: dict[str, Any],
    *,
    duckdb_path: str,
    duckdb_connection: Any | None = None,
) -> bool:
    """Return True when the report may be suggested to analysts (Prompt 196)."""
    rule = report_dict.get("suggested_rule")
    if not isinstance(rule, dict):
        report_dict["analyst_suggestion_allowed"] = False
        report_dict["backtest_validation"] = {
            "passed": False,
            "block_reason": "missing_suggested_rule",
            "analyst_suggestion_allowed": False,
        }
        return False

    if not _backtest_gate_enabled():
        report_dict["analyst_suggestion_allowed"] = True
        return True

    try:
        from shadow_agent.hypothesis_backtest_client import validate_suggested_rule_for_analyst

        validation = validate_suggested_rule_for_analyst(
            rule,
            duckdb_path=duckdb_path,
            duckdb_connection=duckdb_connection,
        )
    except Exception:
        logger.exception("scout_hypothesis_backtest_gate_failed")
        validation = {
            "passed": False,
            "false_positive_rate": 1.0,
            "block_reason": "backtest_gate_error",
            "analyst_suggestion_allowed": False,
        }

    report_dict["backtest_validation"] = validation
    report_dict["backtest_false_positive_rate"] = validation.get("false_positive_rate")
    report_dict["backtest_lookback_days"] = validation.get("lookback_days")
    allowed = bool(validation.get("analyst_suggestion_allowed"))
    report_dict["analyst_suggestion_allowed"] = allowed
    return allowed


def _confidence_from_count(distinct_accounts: int, min_accounts: int) -> float:
    excess = max(0, distinct_accounts - min_accounts)
    return round(min(0.98, 0.55 + excess * 0.06), 3)


def scan_coordinated_bursts(
    *,
    duckdb_path_override: str | None = None,
    min_distinct_accounts: int | None = None,
    window_hours: int | None = None,
    lookback_hours: int | None = None,
) -> dict[str, Any]:
    """
    Query DuckDB ``raw_signals`` for coordinated hardware bursts.

    Returns probe metadata plus ``hypothesis_reports`` (list of :class:`HypothesisReport` dicts).
    """
    path = (duckdb_path_override or duckdb_path()).strip()
    min_accts = (
        min_distinct_accounts if min_distinct_accounts is not None else _min_distinct_accounts()
    )
    win_h = window_hours if window_hours is not None else _window_hours()
    lookback = lookback_hours if lookback_hours is not None else _lookback_hours()

    out: dict[str, Any] = {
        "strategy": "coordinated_burst",
        "duckdb_path": path,
        "duckdb_path_configured": bool(path),
        "min_distinct_accounts": min_accts,
        "window_hours": win_h,
        "lookback_hours": lookback,
        "bursts_found": 0,
        "hypothesis_reports": [],
        "hypothesis_reports_blocked": [],
        "error": None,
    }
    if not path:
        out["error"] = "duckdb_path_not_configured"
        return out

    try:
        import duckdb
    except ImportError:
        out["error"] = "duckdb_import_failed"
        logger.warning("scout_coordinated_burst_duckdb_import_failed")
        return out

    try:
        con = duckdb.connect(path, read_only=True)
    except Exception as exc:
        out["error"] = "duckdb_connect_failed"
        logger.exception("scout_coordinated_burst_connect_failed path=%s", path)
        out["connect_detail"] = str(exc)
        return out

    try:
        tables = {str(r[0]) for r in con.execute("SHOW TABLES").fetchall()}
        if "raw_signals" not in tables:
            out["error"] = "raw_signals_table_missing"
            return out

        sql = f"""
        WITH parsed AS (
            SELECT
                ingested_at,
                CAST(session_id AS VARCHAR) AS session_id,
                COALESCE(
                    NULLIF(TRIM(json_extract_string(signal_json, '$.metadata.acc_id')), ''),
                    NULLIF(TRIM(json_extract_string(signal_json, '$.acc_id')), ''),
                    NULLIF(TRIM(json_extract_string(signal_json, '$.metadata.user_id')), ''),
                    NULLIF(TRIM(json_extract_string(signal_json, '$.user_id')), ''),
                    NULLIF(TRIM(json_extract_string(signal_json, '$.metadata.entity_id')), ''),
                    CAST(session_id AS VARCHAR)
                ) AS acc_id,
                NULLIF(TRIM(COALESCE(
                    json_extract_string(signal_json, '$.ch'),
                    json_extract_string(signal_json, '$.canvas_hash')
                )), '') AS canvas_hash,
                NULLIF(TRIM(COALESCE(
                    json_extract_string(signal_json, '$.wv'),
                    json_extract_string(signal_json, '$.webgl_vendor')
                )), '') AS webgl_vendor
            FROM raw_signals
            WHERE ingested_at >= (CURRENT_TIMESTAMP - INTERVAL '{int(lookback)}' HOUR)
        ),
        events AS (
            SELECT ingested_at, acc_id, 'canvas_hash' AS fp_kind, canvas_hash AS fp_value
            FROM parsed WHERE canvas_hash IS NOT NULL
            UNION ALL
            SELECT ingested_at, acc_id, 'webgl_vendor' AS fp_kind, webgl_vendor AS fp_value
            FROM parsed WHERE webgl_vendor IS NOT NULL
        ),
        windowed AS (
            SELECT
                e1.fp_kind,
                e1.fp_value,
                e1.ingested_at AS window_end,
                e1.ingested_at - INTERVAL '{int(win_h)}' HOUR AS window_start,
                COUNT(DISTINCT e2.acc_id) AS distinct_accounts,
                LIST(DISTINCT e2.acc_id) AS account_ids
            FROM events e1
            INNER JOIN events e2
                ON e1.fp_kind = e2.fp_kind
                AND e1.fp_value = e2.fp_value
                AND e2.ingested_at BETWEEN e1.ingested_at - INTERVAL '{int(win_h)}' HOUR
                    AND e1.ingested_at
            GROUP BY e1.fp_kind, e1.fp_value, e1.ingested_at
            HAVING COUNT(DISTINCT e2.acc_id) >= {int(min_accts)}
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY fp_kind, fp_value
                    ORDER BY distinct_accounts DESC, window_end DESC
                ) AS rn
            FROM windowed
        )
        SELECT
            fp_kind,
            fp_value,
            window_start,
            window_end,
            distinct_accounts,
            account_ids
        FROM ranked
        WHERE rn = 1
        ORDER BY distinct_accounts DESC, window_end DESC
        LIMIT 50
        """
        rows = con.execute(sql).fetchall()
    except Exception as exc:
        out["error"] = "duckdb_query_failed"
        logger.exception("scout_coordinated_burst_query_failed")
        out["query_detail"] = str(exc)
        return out
    finally:
        con.close()

    candidates: list[dict[str, Any]] = []
    for fp_kind, fp_value, window_start, window_end, distinct_accounts, account_ids in rows:
        kind: FingerprintKind = "canvas_hash" if str(fp_kind) == "canvas_hash" else "webgl_vendor"
        acc_list_raw = account_ids if isinstance(account_ids, list) else []
        acc_ids = [str(a) for a in acc_list_raw if a is not None][:_MAX_ACCOUNT_IDS]
        ws = window_start if isinstance(window_start, datetime) else datetime.now(UTC)
        we = window_end if isinstance(window_end, datetime) else datetime.now(UTC)
        if ws.tzinfo is None:
            ws = ws.replace(tzinfo=UTC)
        if we.tzinfo is None:
            we = we.replace(tzinfo=UTC)
        narrative = format_burst_narrative(
            fingerprint_kind=kind,
            fingerprint_value=str(fp_value),
            distinct_account_count=int(distinct_accounts),
            window_hours=win_h,
            window_start=ws,
            window_end=we,
        )
        suggested = suggested_shadow_rule(
            fingerprint_kind=kind,
            fingerprint_value=str(fp_value),
        )
        candidate = HypothesisReport(
            report_id=str(uuid.uuid4()),
            strategy="coordinated_burst",
            fingerprint_kind=kind,
            fingerprint_value=str(fp_value),
            distinct_account_count=int(distinct_accounts),
            window_start_utc=ws,
            window_end_utc=we,
            account_ids=acc_ids,
            narrative=narrative,
            confidence=_confidence_from_count(int(distinct_accounts), min_accts),
            suggested_rule=suggested,
            analyst_suggestion_allowed=False,
        )
        candidates.append(candidate.model_dump(mode="json"))

    reports: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    gate_con = None
    if _backtest_gate_enabled() and candidates:
        try:
            import duckdb

            gate_con = duckdb.connect(path, read_only=True)
        except Exception:
            gate_con = None

    try:
        for candidate in candidates:
            allowed = _apply_backtest_gate(
                candidate,
                duckdb_path=path,
                duckdb_connection=gate_con,
            )
            if allowed:
                reports.append(candidate)
            else:
                blocked.append(candidate)
    finally:
        if gate_con is not None:
            gate_con.close()

    out["bursts_found"] = len(candidates)
    out["hypothesis_reports"] = reports
    out["hypothesis_reports_blocked"] = blocked
    return out


def _saarthi_narrative_mode() -> str:
    return (os.environ.get("SHADOW_SCOUT_SAARTHI_NARRATIVE") or "auto").strip().lower()


def _maybe_attach_saarthi_narratives(payload: dict[str, Any]) -> None:
    mode = _saarthi_narrative_mode()
    if mode in ("off", "disabled", "false", "0"):
        return
    if not payload.get("hypothesis_reports"):
        return
    try:
        from saarthi.hypothesis_narrative import attach_narratives_to_scout_result
    except ImportError:
        logger.debug("scout_saarthi_narrative_skipped_saarthi_package_unavailable")
        return
    attach_narratives_to_scout_result(payload, prefer_gemini=mode != "fallback_only")


def run_scout_coordinated_burst_probe() -> dict[str, Any]:
    """Entry point for agent wiring: scan + compact summary for prompts."""
    payload = scan_coordinated_bursts()
    reports = payload.get("hypothesis_reports") or []
    if reports:
        _maybe_attach_saarthi_narratives(payload)
    payload["scout_summary"] = (
        f"{len(reports)} coordinated burst(s) detected in DuckDB raw_signals."
        if reports
        else "No coordinated canvas_hash/webgl_vendor bursts above threshold."
    )
    if reports:
        first = reports[0] if isinstance(reports[0], dict) else {}
        saarthi = first.get("saarthi_narrative")
        if isinstance(saarthi, str) and saarthi.strip():
            payload["scout_summary"] = saarthi.strip()
    return payload
