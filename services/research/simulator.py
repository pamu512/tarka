"""
DuckDB what-if simulation for proposed Tarka JSON rules (Prompt 193).

Compiles a rule's flat ``when`` clause into SQL over ``raw_signals.signal_json``,
optionally post-filters ``when_ast`` rules in Python (Rust parity via ``tarka_rule_engine``
when installed). Classifies distinct user/session keys against Postgres
``lifecycle_cases`` labels:

* **TP** — rule matches a user/session tied to known fraud (open or confirmed case).
* **FP** — rule matches a user/session with **no** lifecycle case on record.
* **FN** / **TN** — fraud missed and clean non-matches (full 2×2 matrix).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DUCKDB_PATH = os.environ.get("SIGNAL_DUCKDB_PATH", "transactions.duckdb")
DEFAULT_BACKTEST_LOOKBACK_DAYS = 7
MAX_ANALYST_SUGGESTION_FALSE_POSITIVE_RATE = 0.001  # 0.1% — Prompt 196 safety gate

# lifecycle_cases.status values treated as ground-truth fraud for TP/FN.
FRAUD_CASE_STATUSES: frozenset[str] = frozenset(
    {"OPEN", "UNDER_REVIEW", "PENDING_ACTION", "RESOLVED_FRAUD"},
)

# UnifiedSignalSchema wire aliases (``signal_json`` is dumped with by_alias=True).
_ALIAS_TO_CANONICAL: dict[str, str] = {
    "ch": "canvas_hash",
    "wv": "webgl_vendor",
    "dm": "device_memory",
    "ip": "client_ip",
    "px": "is_proxy",
    "ua": "user_agent",
    "sid": "session_id",
    "ts": "timestamp",
    "sv": "sdk_version",
    "mv": "mouse_velocity",
    "tp": "touch_points",
    "hh": "is_headless",
    "gc": "geo_country_code",
    "gct": "geo_city_name",
}

_CANONICAL_TO_ALIAS = {v: k for k, v in _ALIAS_TO_CANONICAL.items()}

# Rule ``field`` → DuckDB json path (canonical names resolve to wire aliases).
_FIELD_JSON_PATHS: dict[str, str] = {
    **{alias: f"$.{alias}" for alias in _ALIAS_TO_CANONICAL},
    **{
        canon: f"$.{_CANONICAL_TO_ALIAS[canon]}"
        for canon in _CANONICAL_TO_ALIAS
        if canon in _CANONICAL_TO_ALIAS
    },
    # Common decision-api / enrichment fields (may appear in metadata merges).
    "amount": "$.amount",
    "currency": "$.currency",
    "is_vpn": "$.is_vpn",
    "is_emulator": "$.is_emulator",
    "is_bot": "$.is_bot",
    "is_new_device": "$.is_new_device",
    "account_age_days": "$.account_age_days",
    "transaction_count_24h": "$.transaction_count_24h",
    "event_count_5m": "$.event_count_5m",
    "event_count_1h": "$.event_count_1h",
    "entity_id": "$.entity_id",
    "user_id": "$.user_id",
}

_SAFE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class LabelSets:
    """Postgres-derived ground truth keyed by user_link_key / entity_id / session id."""

    fraud_keys: frozenset[str]
    cased_keys: frozenset[str]


@dataclass(frozen=True)
class ConfusionMatrix:
    tp: int
    fp: int
    fn: int
    tn: int

    def as_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn}


@dataclass(frozen=True)
class BacktestValidation:
    """Automated backtest gate for analyst-facing hypothesis suggestions (Prompt 196)."""

    passed: bool
    false_positive_rate: float
    lookback_days: int
    max_false_positive_rate: float
    confusion_matrix: ConfusionMatrix
    population_users: int
    matched_users: int
    block_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "false_positive_rate": self.false_positive_rate,
            "lookback_days": self.lookback_days,
            "max_false_positive_rate": self.max_false_positive_rate,
            "confusion_matrix": self.confusion_matrix.as_dict(),
            "population_users": self.population_users,
            "matched_users": self.matched_users,
            "block_reason": self.block_reason,
            "analyst_suggestion_allowed": self.passed,
        }


@dataclass(frozen=True)
class SimulationReport:
    rule_id: str
    sql_predicate: str | None
    evaluated_via: str
    population_users: int
    matched_users: int
    confusion_matrix: ConfusionMatrix
    precision: float
    recall: float
    f1_score: float

    def as_dict(self) -> dict[str, Any]:
        cm = self.confusion_matrix
        return {
            "rule_id": self.rule_id,
            "evaluated_via": self.evaluated_via,
            "sql_predicate": self.sql_predicate,
            "population_users": self.population_users,
            "matched_users": self.matched_users,
            "confusion_matrix": cm.as_dict(),
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
        }


def _json_path_for_field(field: str) -> str:
    if field in _FIELD_JSON_PATHS:
        return _FIELD_JSON_PATHS[field]
    if _SAFE_FIELD.match(field):
        return f"$.{field}"
    raise ValueError(f"unsupported rule field name: {field!r}")


def _sql_json_expr(signal_col: str, field: str) -> str:
    path = _json_path_for_field(field)
    return f"json_extract({signal_col}, '{path}')"


def _sql_json_string_expr(signal_col: str, field: str) -> str:
    path = _json_path_for_field(field)
    return f"json_extract_string({signal_col}, '{path}')"


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(float(value) if isinstance(value, float) else value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(value, list):
        inner = ", ".join(_sql_literal(v) for v in value)
        return f"[{inner}]"
    raise TypeError(f"cannot encode SQL literal for {type(value).__name__}")


def condition_to_sql(cond: dict[str, Any], *, signal_col: str = "signal_json") -> str:
    """Compile one flat ``when`` condition to a DuckDB SQL boolean expression."""
    op = str(cond.get("op") or "eq")
    field = str(cond.get("field") or "")
    if not field:
        return "FALSE"
    expr = _sql_json_expr(signal_col, field)
    str_expr = _sql_json_string_expr(signal_col, field)
    expected = cond.get("value")

    if op == "eq":
        return f"{str_expr} = {_sql_literal(str(expected) if expected is not None else None)}"
    if op == "not_eq":
        return f"{str_expr} IS DISTINCT FROM {_sql_literal(str(expected) if expected is not None else None)}"
    if op in ("gte", "gt", "lte", "lt"):
        cmp = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<"}[op]
        return f"try_cast({expr} AS DOUBLE) {cmp} {_sql_literal(expected)}"
    if op == "in":
        vals = expected if isinstance(expected, list) else []
        if not vals:
            return "FALSE"
        parts = [f"{str_expr} = {_sql_literal(str(v))}" for v in vals]
        return "(" + " OR ".join(parts) + ")"
    if op == "not_in":
        vals = expected if isinstance(expected, list) else []
        if not vals:
            return "TRUE"
        parts = [f"{str_expr} = {_sql_literal(str(v))}" for v in vals]
        return "NOT (" + " OR ".join(parts) + ")"
    if op == "contains":
        needle = str(expected or "")
        if not needle:
            return "FALSE"
        esc = needle.replace("'", "''")
        return f"strpos(COALESCE(try_cast({expr} AS VARCHAR), ''), '{esc}') > 0"
    if op == "starts_with":
        prefix = str(expected or "")
        esc = prefix.replace("'", "''")
        return f"startswith(COALESCE(try_cast({expr} AS VARCHAR), ''), '{esc}')"
    if op == "ends_with":
        suffix = str(expected or "")
        esc = suffix.replace("'", "''")
        return f"endswith(COALESCE(try_cast({expr} AS VARCHAR), ''), '{esc}')"
    if op == "is_true":
        return f"try_cast({expr} AS BOOLEAN) IS TRUE"
    if op == "is_false":
        return f"try_cast({expr} AS BOOLEAN) IS FALSE"
    if op == "exists":
        return f"{expr} IS NOT NULL"
    if op == "not_exists":
        return f"{expr} IS NULL"
    raise ValueError(f"unsupported rule op: {op!r}")


def rule_flat_when_to_sql(rule: dict[str, Any], *, signal_col: str = "signal_json") -> str | None:
    when = rule.get("when")
    if not isinstance(when, list) or not when:
        return None
    parts: list[str] = []
    for cond in when:
        if not isinstance(cond, dict):
            return None
        parts.append(condition_to_sql(cond, signal_col=signal_col))
    return " AND ".join(f"({p})" for p in parts)


def normalize_rule(doc: dict[str, Any]) -> dict[str, Any]:
    """Accept a single rule or a ruleset envelope with ``rules: [...]``."""
    if "rules" in doc and isinstance(doc["rules"], list):
        rules = doc["rules"]
        if not rules:
            raise ValueError("ruleset has no rules")
        if len(rules) > 1:
            logger.warning("simulator using first rule only (%d rules in file)", len(rules))
        first = rules[0]
        if not isinstance(first, dict):
            raise ValueError("rules[0] must be an object")
        return first
    return doc


def signal_features_from_json(signal_json: str) -> dict[str, Any]:
    """Parse ``signal_json`` and expose both wire aliases and canonical names."""
    raw = json.loads(signal_json)
    if not isinstance(raw, dict):
        return {}
    features: dict[str, Any] = dict(raw)
    for alias, canon in _ALIAS_TO_CANONICAL.items():
        if alias in raw:
            features[canon] = raw[alias]
        elif canon in raw:
            features[alias] = raw[canon]
    meta = raw.get("metadata")
    if isinstance(meta, dict):
        features.update(meta)
    return features


def signal_user_key(session_id: str, features: dict[str, Any]) -> str:
    """Dedup key aligned with orchestrator ``user_link_key`` resolution."""
    for path in (
        ("user_id",),
        ("entity_id",),
        ("user_link_key",),
        ("metadata", "user_id"),
        ("metadata", "entity_id"),
    ):
        cur: Any = features
        for part in path:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(part)
        if cur is not None and str(cur).strip():
            return str(cur).strip()
    sid = features.get("session_id") or features.get("sid")
    if sid is not None and str(sid).strip():
        return str(sid).strip()
    return str(session_id).strip()


def fetch_label_sets_from_postgres(database_url: str) -> LabelSets:
    import psycopg

    fraud: set[str] = set()
    cased: set[str] = set()
    fraud_list = sorted(FRAUD_CASE_STATUSES)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT user_link_key, entity_id, linked_session_id, status
                FROM lifecycle_cases
                """,
            )
            for user_link_key, entity_id, linked_session_id, status in cur.fetchall():
                status_u = str(status or "").strip().upper()
                for key in (user_link_key, entity_id, linked_session_id):
                    if key is None:
                        continue
                    s = str(key).strip()
                    if not s:
                        continue
                    cased.add(s)
                    if status_u in FRAUD_CASE_STATUSES:
                        fraud.add(s)
    return LabelSets(fraud_keys=frozenset(fraud), cased_keys=frozenset(cased))


def _rule_matches_python(rule: dict[str, Any], features: dict[str, Any]) -> bool:
    if rule.get("when_ast") is not None:
        try:
            from tarka_rule_engine import evaluate_observation_rules_json

            payload = json.loads(
                evaluate_observation_rules_json(
                    json.dumps([rule], default=str),
                    json.dumps(features, default=str),
                ),
            )
            rid = str(rule.get("id") or "")
            shadow = payload.get("shadow_results") or {}
            if rid and shadow.get(rid):
                return True
            matched = payload.get("matched_rule_ids") or []
            return rid in matched if rid else bool(shadow)
        except ImportError:
            pass
    try:
        from tarka_v2_core.shadow_hypothesis import rule_matches_flat

        return rule_matches_flat(rule, features)
    except ImportError:
        when = rule.get("when")
        if not isinstance(when, list) or not when:
            return False
        from tarka_v2_core.shadow_hypothesis import match_flat_condition

        return all(isinstance(c, dict) and match_flat_condition(features, c) for c in when)


def _lookback_filter_sql(lookback_days: int | None) -> str:
    if lookback_days is None or lookback_days <= 0:
        return ""
    days = int(lookback_days)
    return f" WHERE ingested_at >= (CURRENT_TIMESTAMP - INTERVAL '{days}' DAY)"


def compute_false_positive_rate(cm: ConfusionMatrix) -> float:
    """FPR among non-fraud ground-truth negatives: ``fp / (fp + tn)``."""
    denom = cm.fp + cm.tn
    if denom <= 0:
        return 0.0
    return cm.fp / denom


def collect_matched_entity_ids(
    rule: dict[str, Any],
    *,
    duckdb_path: str | Path = DEFAULT_DUCKDB_PATH,
    lookback_days: int | None = DEFAULT_BACKTEST_LOOKBACK_DAYS,
    duckdb_connection: Any | None = None,
) -> list[str]:
    """
    Distinct user/entity keys that matched ``rule`` over the backtest window (Prompt 200).

    Used to harden JanusGraph after an observation rule is promoted to production.
    """
    import duckdb

    sql_predicate = rule_flat_when_to_sql(rule)
    own_con = duckdb_connection is None
    con = duckdb_connection or duckdb.connect(str(duckdb_path))
    try:
        tables = {str(r[0]) for r in con.execute("SHOW TABLES").fetchall()}
        if "raw_signals" not in tables:
            return []
        matched, _population = _population_and_matches(
            con,
            rule,
            sql_predicate=sql_predicate,
            lookback_days=lookback_days,
        )
        return sorted(k for k, hit in matched.items() if hit)
    finally:
        if own_con:
            con.close()


def _population_and_matches(
    con: Any,
    rule: dict[str, Any],
    *,
    sql_predicate: str | None,
    lookback_days: int | None = None,
) -> tuple[dict[str, bool], dict[str, dict[str, Any]]]:
    """
    Returns ``user_key -> matched`` for every user seen in ``raw_signals``,
    plus latest features per user (for Python AST pass).
    """
    lookback = _lookback_filter_sql(lookback_days)
    rows = con.execute(
        f"SELECT session_id, signal_json FROM raw_signals{lookback} ORDER BY ingested_at DESC",
    ).fetchall()

    population: dict[str, dict[str, Any]] = {}
    for session_id, signal_json in rows:
        sid = str(session_id)
        try:
            features = signal_features_from_json(str(signal_json))
        except json.JSONDecodeError:
            features = {}
        ukey = signal_user_key(sid, features)
        if ukey not in population:
            population[ukey] = features

    matched: dict[str, bool] = dict.fromkeys(population, False)

    if sql_predicate and rule.get("when_ast") is None:
        if lookback_days is not None and lookback_days > 0:
            time_clause = (
                f"ingested_at >= (CURRENT_TIMESTAMP - INTERVAL '{int(lookback_days)}' DAY) AND "
            )
        else:
            time_clause = ""
        hit_rows = con.execute(
            f"""
            SELECT DISTINCT session_id, signal_json
            FROM raw_signals
            WHERE {time_clause}({sql_predicate})
            """,
        ).fetchall()
        for session_id, signal_json in hit_rows:
            sid = str(session_id)
            try:
                features = signal_features_from_json(str(signal_json))
            except json.JSONDecodeError:
                features = {}
            ukey = signal_user_key(sid, features)
            if ukey in matched:
                matched[ukey] = True
        return matched, population

    for ukey, features in population.items():
        matched[ukey] = _rule_matches_python(rule, features)
    return matched, population


def build_confusion_matrix(
    matched: dict[str, bool],
    labels: LabelSets,
) -> ConfusionMatrix:
    tp = fp = fn = tn = 0
    for ukey, hit in matched.items():
        is_fraud = ukey in labels.fraud_keys
        has_case = ukey in labels.cased_keys
        if hit and is_fraud:
            tp += 1
        elif hit and not has_case:
            fp += 1
        elif not hit and is_fraud:
            fn += 1
        elif not hit and not has_case:
            tn += 1
        # Users with a non-fraud case (e.g. RESOLVED_LEGIT) who match are intentionally
        # excluded from TP/FP/FN/TN — they are neither "known fraud" nor "no case".
    return ConfusionMatrix(tp=tp, fp=fp, fn=fn, tn=tn)


def run_what_if_simulation(
    rule: dict[str, Any],
    *,
    duckdb_path: str | Path = DEFAULT_DUCKDB_PATH,
    postgres_url: str | None = None,
    labels: LabelSets | None = None,
    duckdb_connection: Any | None = None,
    lookback_days: int | None = None,
) -> SimulationReport:
    """
      Run the what-if simulation and return a structured report.

    ``labels`` may be supplied for tests; otherwise ``postgres_url`` (or
      ``ORCHESTRATOR_AUDIT_DATABASE_URL`` / ``DATABASE_URL``) is required.
    """
    import duckdb

    rule_id = str(rule.get("id") or "unnamed")
    sql_predicate = rule_flat_when_to_sql(rule)
    evaluated_via = "duckdb_sql"
    if rule.get("when_ast") is not None:
        evaluated_via = "python_when_ast"
    elif sql_predicate is None:
        evaluated_via = "python_flat_when"

    if labels is None:
        url = (
            postgres_url
            or os.environ.get("ORCHESTRATOR_AUDIT_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
        )
        if not url:
            raise ValueError(
                "postgres_url or ORCHESTRATOR_AUDIT_DATABASE_URL required when labels not provided",
            )
        labels = fetch_label_sets_from_postgres(url)

    own_con = duckdb_connection is None
    con = duckdb_connection or duckdb.connect(str(duckdb_path))
    try:
        tables = {str(r[0]) for r in con.execute("SHOW TABLES").fetchall()}
        if "raw_signals" not in tables:
            raise ValueError(f"raw_signals table not found in {duckdb_path}")

        matched, _population = _population_and_matches(
            con,
            rule,
            sql_predicate=sql_predicate,
            lookback_days=lookback_days,
        )
        cm = build_confusion_matrix(matched, labels)
        precision = cm.tp / max(cm.tp + cm.fp, 1)
        recall = cm.tp / max(cm.tp + cm.fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-8)
        return SimulationReport(
            rule_id=rule_id,
            sql_predicate=sql_predicate,
            evaluated_via=evaluated_via,
            population_users=len(matched),
            matched_users=sum(1 for v in matched.values() if v),
            confusion_matrix=cm,
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1_score=round(f1, 4),
        )
    finally:
        if own_con:
            con.close()


def _production_blocked(features: dict[str, Any]) -> bool:
    """Heuristic: signal carried a production deny/review/block decision in metadata."""
    meta = features.get("metadata") if isinstance(features.get("metadata"), dict) else {}
    for key in (
        "production_decision",
        "decision",
        "rule_result",
        "orchestrator_fallback_decision",
    ):
        for src in (features, meta):
            if not isinstance(src, dict):
                continue
            raw = src.get(key)
            if raw is None:
                continue
            val = str(raw).strip().upper()
            if val in ("DENY", "BLOCK", "REVIEW", "FLAG", "SHADOW_REVIEW"):
                return True
    if features.get("is_blocked") is True or meta.get("is_blocked") is True:
        return True
    return False


def _hour_bucket_key(ingested_at: Any) -> str:
    if isinstance(ingested_at, datetime):
        dt = ingested_at
    else:
        text = str(ingested_at).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return text[:13] if len(text) >= 13 else text
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    dt = dt.replace(minute=0, second=0, microsecond=0)
    return dt.isoformat(sep=" ", timespec="hours")


def build_block_overlay_timeseries(
    rule: dict[str, Any],
    *,
    duckdb_path: str | Path = DEFAULT_DUCKDB_PATH,
    duckdb_connection: Any | None = None,
    lookback_days: int | None = None,
) -> list[dict[str, Any]]:
    """
    Hourly buckets for visual backtest overlay (Prompt 198).

    * **production_blocks** — distinct sessions production blocked (metadata heuristic).
    * **shadow_blocks** — distinct sessions the proposed rule would block.
    * **shadow_only_blocks** — shadow catches production missed (new attack wave signal).
    """
    import duckdb

    days = (
        lookback_days
        if lookback_days is not None
        else int(
            os.environ.get("HYPOTHESIS_BACKTEST_LOOKBACK_DAYS", DEFAULT_BACKTEST_LOOKBACK_DAYS),
        )
    )
    sql_predicate = rule_flat_when_to_sql(rule)
    use_sql_shadow = bool(sql_predicate) and rule.get("when_ast") is None

    own_con = duckdb_connection is None
    con = duckdb_connection or duckdb.connect(str(duckdb_path))
    try:
        lookback = _lookback_filter_sql(days)
        rows = con.execute(
            f"SELECT ingested_at, session_id, signal_json FROM raw_signals{lookback} ORDER BY ingested_at",
        ).fetchall()

        prod_by_hour: dict[str, set[str]] = {}
        shadow_by_hour: dict[str, set[str]] = {}

        for ingested_at, session_id, signal_json in rows:
            bucket = _hour_bucket_key(ingested_at)
            try:
                features = signal_features_from_json(str(signal_json))
            except json.JSONDecodeError:
                features = {}
            ukey = signal_user_key(str(session_id), features)

            if _production_blocked(features):
                prod_by_hour.setdefault(bucket, set()).add(ukey)

            shadow_hit = False
            if use_sql_shadow and sql_predicate:
                # Row-level SQL check deferred: batch via precomputed set below
                shadow_hit = False
            else:
                shadow_hit = _rule_matches_python(rule, features)

            if shadow_hit:
                shadow_by_hour.setdefault(bucket, set()).add(ukey)

        if use_sql_shadow and sql_predicate:
            time_clause = (
                f"ingested_at >= (CURRENT_TIMESTAMP - INTERVAL '{int(days)}' DAY) AND "
                if days > 0
                else ""
            )
            hit_rows = con.execute(
                f"""
                SELECT ingested_at, session_id, signal_json
                FROM raw_signals
                WHERE {time_clause}({sql_predicate})
                """,
            ).fetchall()
            shadow_by_hour = {}
            for ingested_at, session_id, signal_json in hit_rows:
                bucket = _hour_bucket_key(ingested_at)
                try:
                    features = signal_features_from_json(str(signal_json))
                except json.JSONDecodeError:
                    features = {}
                ukey = signal_user_key(str(session_id), features)
                shadow_by_hour.setdefault(bucket, set()).add(ukey)

        all_buckets = sorted(set(prod_by_hour) | set(shadow_by_hour))
        series: list[dict[str, Any]] = []
        for bucket in all_buckets:
            prod_set = prod_by_hour.get(bucket, set())
            shadow_set = shadow_by_hour.get(bucket, set())
            shadow_only = shadow_set - prod_set
            series.append(
                {
                    "bucket": bucket,
                    "label": bucket,
                    "production_blocks": len(prod_set),
                    "shadow_blocks": len(shadow_set),
                    "shadow_only_blocks": len(shadow_only),
                },
            )
        return series
    finally:
        if own_con:
            con.close()


def validate_hypothesis_backtest(
    rule: dict[str, Any],
    *,
    duckdb_path: str | Path = DEFAULT_DUCKDB_PATH,
    postgres_url: str | None = None,
    labels: LabelSets | None = None,
    duckdb_connection: Any | None = None,
    lookback_days: int | None = None,
    max_false_positive_rate: float | None = None,
) -> BacktestValidation:
    """
    Safety gate (Prompt 196): hypothesis may be suggested to analysts only when
    DuckDB backtest FPR is strictly below ``max_false_positive_rate`` (default 0.1%)
    over the last ``lookback_days`` (default 7).
    """
    days = (
        lookback_days
        if lookback_days is not None
        else int(
            os.environ.get("HYPOTHESIS_BACKTEST_LOOKBACK_DAYS", DEFAULT_BACKTEST_LOOKBACK_DAYS),
        )
    )
    max_fpr = max_false_positive_rate
    if max_fpr is None:
        raw = (os.environ.get("HYPOTHESIS_MAX_FALSE_POSITIVE_RATE") or "").strip()
        max_fpr = float(raw) if raw else MAX_ANALYST_SUGGESTION_FALSE_POSITIVE_RATE

    try:
        sim = run_what_if_simulation(
            rule,
            duckdb_path=duckdb_path,
            postgres_url=postgres_url,
            labels=labels,
            duckdb_connection=duckdb_connection,
            lookback_days=days,
        )
    except ValueError as exc:
        return BacktestValidation(
            passed=False,
            false_positive_rate=1.0,
            lookback_days=days,
            max_false_positive_rate=max_fpr,
            confusion_matrix=ConfusionMatrix(tp=0, fp=0, fn=0, tn=0),
            population_users=0,
            matched_users=0,
            block_reason=str(exc),
        )

    fpr = compute_false_positive_rate(sim.confusion_matrix)
    passed = fpr < max_fpr
    block_reason = None if passed else "false_positive_rate_exceeds_threshold"
    return BacktestValidation(
        passed=passed,
        false_positive_rate=round(fpr, 6),
        lookback_days=days,
        max_false_positive_rate=max_fpr,
        confusion_matrix=sim.confusion_matrix,
        population_users=sim.population_users,
        matched_users=sim.matched_users,
        block_reason=block_reason,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DuckDB what-if simulation for a proposed Tarka JSON rule.",
    )
    parser.add_argument(
        "--rule",
        required=True,
        help="Path to JSON rule or ruleset file.",
    )
    parser.add_argument(
        "--duckdb",
        default=DEFAULT_DUCKDB_PATH,
        help=f"Path to DuckDB file (default: {DEFAULT_DUCKDB_PATH}).",
    )
    parser.add_argument(
        "--postgres-url",
        default=None,
        help="Postgres URL for lifecycle_cases labels (else ORCHESTRATOR_AUDIT_DATABASE_URL).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON result.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    rule_path = Path(args.rule)
    doc = json.loads(rule_path.read_text(encoding="utf-8"))
    rule = normalize_rule(doc)
    report = run_what_if_simulation(
        rule,
        duckdb_path=args.duckdb,
        postgres_url=args.postgres_url,
    )
    indent = 2 if args.pretty else None
    print(json.dumps(report.as_dict(), indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
