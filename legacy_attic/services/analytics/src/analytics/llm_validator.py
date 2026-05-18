"""ClickHouse LLM SQL guardrails: schema registry, sqlglot lint, tenant segregation, execution caps."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from analytics.queries import _normalize_clickhouse_named_params

# Fallback when sqlglot cannot parse (obfuscated attacks). Not applied to successfully parsed SELECTs
# so literals like ``SELECT 'DROP TABLE'`` are not false positives.
_FORBIDDEN_LEX = re.compile(
    r"\b(?:DROP|TRUNCATE|ALTER|INSERT|DELETE|ATTACH|DETACH|OPTIMIZE|SYSTEM|GRANT|REVOKE|EXECUTE|CREATE|RENAME)\b",
    re.IGNORECASE,
)


def _forbidden_statement_node_types() -> tuple[type[exp.Expression], ...]:
    types: list[type[exp.Expression]] = [
        exp.Insert,
        exp.Delete,
        exp.Update,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Command,
    ]
    tr = getattr(exp, "Truncate", None)
    if tr is not None:
        types.append(tr)
    rn = getattr(exp, "Rename", None)
    if rn is not None:
        types.append(rn)
    return tuple(types)


def _ast_forbidden_ddl_dml(root: exp.Expression) -> list[str]:
    """Parser-level block: any DDL/DML node under the tree is rejected (SELECT/UNION only)."""
    forbidden = _forbidden_statement_node_types()
    seen: set[str] = set()
    out: list[str] = []
    for node in root.walk():
        if isinstance(node, forbidden):
            tag = f"forbidden_statement:{type(node).__name__.lower()}"
            if tag not in seen:
                seen.add(tag)
                out.append(tag)
    return out


def _where_has_tenant_bind(sql_fragment: str) -> bool:
    """True if the fragment already binds ``tenant_id`` via clickhouse_connect-style placeholder."""
    return "{tenant_id:String}" in _normalize_clickhouse_named_params(sql_fragment)


_SETTINGS_MAX_EXEC = re.compile(
    r"\bSETTINGS\b[\s\S]*\bmax_execution_time\s*=\s*(\d+)",
    re.IGNORECASE,
)


class AnalyticsSqlUnsafeError(Exception):
    """Raised when LLM SQL fails lint; messages map to ``503 ANALYTICS_QUERY_UNSAFE``."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(errors[0] if errors else "unsafe_sql")


@dataclass
class ClickHouseSchemaRegistry:
    """Authoritative table → column → ClickHouse type (for NL SQL linting)."""

    tables: dict[str, dict[str, str]] = field(default_factory=dict)

    def register_table(self, name: str, columns: dict[str, str]) -> None:
        self.tables[name] = dict(columns)

    def ddl_for_table(self, table: str) -> str:
        if table not in self.tables:
            raise KeyError(table)
        cols = ",\n  ".join(f"`{c}` {t}" for c, t in sorted(self.tables[table].items()))
        return f"CREATE TABLE `{table}` (\n  {cols}\n) ENGINE = MergeTree ORDER BY tuple();"

    def full_ddl_document(self) -> str:
        return "\n\n".join(self.ddl_for_table(t) for t in sorted(self.tables))

    def has_table(self, name: str) -> bool:
        return name in self.tables

    def column_type(self, table: str, column: str) -> str | None:
        t = self.tables.get(table)
        if not t:
            return None
        return t.get(column)


def default_analytics_registry() -> ClickHouseSchemaRegistry:
    """Baseline OLAP tables (conservative types; extend via ``register_table``)."""
    r = ClickHouseSchemaRegistry()
    r.register_table(
        "fraud_decisions",
        {
            "tenant_id": "String",
            "entity_id": "String",
            "trace_id": "String",
            "decision": "String",
            "score": "Float64",
            "tags": "String",
            "rule_hits": "String",
            "created_at": "String",
            "event_type": "String",
        },
    )
    r.register_table(
        "inference_logs_ch",
        {
            "id": "UUID",
            "trace_id": "UUID",
            "tenant_id": "String",
            "entity_id": "String",
            "event_type": "String",
            "decision": "String",
            "score": "Float64",
            "tags": "String",
            "rule_hits": "String",
            "payload_snapshot": "Nullable(String)",
            "created_at": "DateTime64(3, 'UTC')",
            "_version": "DateTime64(3, 'UTC')",
        },
    )
    return r


def _multi_statement(sql: str) -> bool:
    s = sql.strip().rstrip(";")
    return ";" in s


def _iter_selects(root: exp.Expression) -> list[exp.Select]:
    return [n for n in root.walk() if isinstance(n, exp.Select)]


def _physical_tables_in_select(sel: exp.Select) -> set[str]:
    names: set[str] = set()
    frm = sel.args.get("from_")
    if frm and isinstance(frm.this, exp.Table):
        n = frm.this.name
        if n:
            names.add(n)
    for j in sel.args.get("joins") or []:
        if isinstance(j, exp.Join) and isinstance(j.this, exp.Table):
            n = j.this.name
            if n:
                names.add(n)
    return names


def _alias_map(sel: exp.Select) -> dict[str, str]:
    m: dict[str, str] = {}
    frm = sel.args.get("from_")
    if frm and isinstance(frm.this, exp.Table):
        phys = frm.this.name
        if phys:
            m[phys] = phys
            al = frm.this.alias
            if al:
                m[str(al)] = phys
    for j in sel.args.get("joins") or []:
        if isinstance(j, exp.Join) and isinstance(j.this, exp.Table):
            phys = j.this.name
            if phys:
                m[phys] = phys
                al = j.this.alias
                if al:
                    m[str(al)] = phys
    return m


def _from_chain_tables(sel: exp.Select) -> list[str]:
    """Physical table names in FROM + JOIN order (ClickHouse: joins live on ``Select``)."""
    out: list[str] = []
    frm = sel.args.get("from_")
    if frm and isinstance(frm.this, exp.Table) and frm.this.name:
        out.append(frm.this.name)
    for j in sel.args.get("joins") or []:
        if isinstance(j, exp.Join) and isinstance(j.this, exp.Table) and j.this.name:
            out.append(j.this.name)
    return out


def _validate_join_allowlist(sel: exp.Select, allowed: set[frozenset[str]] | None) -> list[str]:
    chain = _from_chain_tables(sel)
    if len(chain) <= 1:
        return []
    if not allowed:
        return ["join_not_allowlisted:JOIN operations require an explicit allow-list"]
    errs: list[str] = []
    for left, right in zip(chain, chain[1:], strict=False):
        edge = frozenset({left, right})
        if edge not in allowed:
            errs.append(f"join_not_allowlisted:{sorted(edge)}")
    return errs


def _all_cte_aliases(root: exp.Expression) -> set[str]:
    names: set[str] = set()
    for w in root.find_all(exp.With):
        for c in w.expressions:
            if isinstance(c, exp.CTE) and c.alias:
                names.add(str(c.alias))
    return names


def _validate_tables_and_columns(
    sel: exp.Select,
    registry: ClickHouseSchemaRegistry,
    *,
    cte_aliases: set[str],
) -> list[str]:
    errs: list[str] = []
    phys_tables = _physical_tables_in_select(sel)
    for t in phys_tables:
        if registry.has_table(t):
            continue
        if t in cte_aliases:
            continue
        errs.append(f"unknown_table:{t}")
    if errs:
        return errs
    alias = _alias_map(sel)
    for col in sel.find_all(exp.Column):
        cname = col.name
        if not cname or cname == "*":
            continue
        tbl_hint = col.table
        phys = alias.get(str(tbl_hint)) if tbl_hint else None
        if phys is None:
            if len(phys_tables) == 1:
                phys = next(iter(phys_tables))
            else:
                errs.append(f"ambiguous_column:{cname}")
                continue
        if phys in cte_aliases:
            continue
        if registry.column_type(phys, cname) is None:
            errs.append(f"unknown_column:{phys}.{cname}")
    return errs


def _select_mentions_registry_table(sel: exp.Select, registry: ClickHouseSchemaRegistry) -> bool:
    return any(registry.has_table(t) for t in _physical_tables_in_select(sel))


def _tenant_predicate_for_select(
    sel: exp.Select, registry: ClickHouseSchemaRegistry
) -> exp.Expression:
    tables = sorted(t for t in _physical_tables_in_select(sel) if registry.has_table(t))
    if not tables:
        return sqlglot.parse_one("1 = 1", dialect="clickhouse")
    if len(tables) == 1:
        return sqlglot.parse_one("tenant_id = {tenant_id:String}", dialect="clickhouse")
    parts: list[exp.Expression] = []
    for t in tables:
        parts.append(
            sqlglot.parse_one(f'"{t}"."tenant_id" = {{tenant_id:String}}', dialect="clickhouse")
        )
    return exp.and_(*parts)


def _inject_tenant_filters(root: exp.Expression, registry: ClickHouseSchemaRegistry) -> None:
    for sel in _iter_selects(root):
        if not _select_mentions_registry_table(sel, registry):
            continue
        frag = _normalize_clickhouse_named_params(sel.sql(dialect="clickhouse", identify=True))
        if _where_has_tenant_bind(frag):
            continue
        cond = _tenant_predicate_for_select(sel, registry)
        w = sel.args.get("where")
        if w:
            sel.set("where", exp.Where(this=exp.and_(w.this, cond)))
        else:
            sel.set("where", exp.Where(this=cond))


def _append_settings_max_exec(sql: str, max_sec: int) -> str:
    base = sql.rstrip().rstrip(";")
    m = _SETTINGS_MAX_EXEC.search(base)
    if m:
        n = int(m.group(1))
        if n > max_sec:
            raise AnalyticsSqlUnsafeError([f"max_execution_time_too_large:{n}>{max_sec}"])
        return base
    sep = " " if base else ""
    return f"{base}{sep}SETTINGS max_execution_time = {int(max_sec)}"


def lint_and_harden_clickhouse_llm_sql(
    sql: str,
    *,
    registry: ClickHouseSchemaRegistry | None = None,
    allowed_join_pairs: Iterable[frozenset[str]] | None = None,
    max_execution_seconds: int = 5,
) -> str:
    """
    Parse LLM SQL (ClickHouse), lint, inject tenant bind(s) (``{tenant_id:String}``), append SETTINGS.

    Raises ``AnalyticsSqlUnsafeError`` for unsafe SQL (caller maps to HTTP 503).
    """
    reg = registry or default_analytics_registry()
    allowed: set[frozenset[str]] | None = None
    if allowed_join_pairs is not None:
        allowed = {frozenset(x) for x in allowed_join_pairs}

    if _multi_statement(sql):
        raise AnalyticsSqlUnsafeError(["multi_statement_not_allowed"])

    try:
        parsed = sqlglot.parse_one(sql, dialect="clickhouse")
    except sqlglot.errors.ParseError as e:
        errs: list[str] = [f"parse_error:{e}"]
        if _FORBIDDEN_LEX.search(sql):
            errs.insert(0, "forbidden_ddl_or_dml_keyword")
        raise AnalyticsSqlUnsafeError(errs) from e

    if not isinstance(parsed, (exp.Select, exp.Union)):
        errs = ["only_select_or_union_allowed"]
        errs.extend(_ast_forbidden_ddl_dml(parsed))
        raise AnalyticsSqlUnsafeError(list(dict.fromkeys(errs)))

    ddl_errs = _ast_forbidden_ddl_dml(parsed)
    if ddl_errs:
        raise AnalyticsSqlUnsafeError(ddl_errs)

    cte_aliases = _all_cte_aliases(parsed)
    all_errs: list[str] = []
    for sel in _iter_selects(parsed):
        all_errs.extend(_validate_join_allowlist(sel, allowed))
        all_errs.extend(_validate_tables_and_columns(sel, reg, cte_aliases=cte_aliases))
    if all_errs:
        raise AnalyticsSqlUnsafeError(list(dict.fromkeys(all_errs)))

    _inject_tenant_filters(parsed, reg)
    sql_out = _normalize_clickhouse_named_params(parsed.sql(dialect="clickhouse", identify=True))
    return _append_settings_max_exec(sql_out, max_execution_seconds)


def validate_nl_sql_for_execution(
    sql: str,
    *,
    registry: ClickHouseSchemaRegistry | None = None,
    allowed_join_pairs: Iterable[frozenset[str]] | None = None,
) -> str:
    """Public alias: ``max_execution_time`` fixed to 5 seconds per policy."""
    return lint_and_harden_clickhouse_llm_sql(
        sql,
        registry=registry,
        allowed_join_pairs=allowed_join_pairs,
        max_execution_seconds=5,
    )
