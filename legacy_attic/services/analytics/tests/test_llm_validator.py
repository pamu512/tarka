"""Pre-execution ClickHouse LLM SQL linter."""

from __future__ import annotations

import pytest
from analytics.llm_validator import (
    AnalyticsSqlUnsafeError,
    ClickHouseSchemaRegistry,
    default_analytics_registry,
    lint_and_harden_clickhouse_llm_sql,
)


def test_blocks_drop_statement_ast() -> None:
    with pytest.raises(AnalyticsSqlUnsafeError) as ei:
        lint_and_harden_clickhouse_llm_sql("DROP TABLE fraud_decisions")
    assert any("forbidden_statement:drop" in e for e in ei.value.errors)


def test_blocks_drop_in_multi_statement() -> None:
    with pytest.raises(AnalyticsSqlUnsafeError) as ei:
        lint_and_harden_clickhouse_llm_sql("SELECT 1; DROP TABLE fraud_decisions")
    assert "multi_statement_not_allowed" in ei.value.errors


def test_allows_drop_substring_in_string_literal() -> None:
    out = lint_and_harden_clickhouse_llm_sql(
        "SELECT 'DROP TABLE' AS hint FROM fraud_decisions WHERE decision = 'block'"
    )
    assert "DROP TABLE" in out
    assert "{tenant_id:String}" in out
    assert "SETTINGS max_execution_time = 5" in out


def test_blocks_join_without_allowlist() -> None:
    sql = "SELECT fd.tenant_id FROM fraud_decisions fd JOIN inference_logs_ch il ON fd.entity_id = il.entity_id"
    with pytest.raises(AnalyticsSqlUnsafeError) as ei:
        lint_and_harden_clickhouse_llm_sql(sql, allowed_join_pairs=None)
    assert any("join_not_allowlisted" in e for e in ei.value.errors)


def test_allows_join_when_allowlisted() -> None:
    sql = "SELECT fd.tenant_id FROM fraud_decisions fd JOIN inference_logs_ch il ON fd.entity_id = il.entity_id"
    out = lint_and_harden_clickhouse_llm_sql(
        sql,
        allowed_join_pairs={frozenset({"fraud_decisions", "inference_logs_ch"})},
    )
    assert '"fraud_decisions"."tenant_id" = {tenant_id:String}' in out
    assert '"inference_logs_ch"."tenant_id" = {tenant_id:String}' in out
    assert "SETTINGS max_execution_time = 5" in out


def test_injects_tenant_and_settings() -> None:
    out = lint_and_harden_clickhouse_llm_sql(
        "SELECT count(*) AS c FROM fraud_decisions WHERE decision = 'block'"
    )
    assert "{tenant_id:String}" in out and "tenant_id" in out
    assert "SETTINGS max_execution_time = 5" in out


def test_unknown_column() -> None:
    with pytest.raises(AnalyticsSqlUnsafeError) as ei:
        lint_and_harden_clickhouse_llm_sql("SELECT not_a_col FROM fraud_decisions")
    assert any("unknown_column" in e for e in ei.value.errors)


def test_registry_ddl_roundtrip() -> None:
    r = default_analytics_registry()
    ddl = r.ddl_for_table("fraud_decisions")
    assert "tenant_id" in ddl and "CREATE TABLE" in ddl


def test_custom_registry_unknown_table() -> None:
    reg = ClickHouseSchemaRegistry()
    reg.register_table("tiny", {"id": "Int32"})
    with pytest.raises(AnalyticsSqlUnsafeError):
        lint_and_harden_clickhouse_llm_sql("SELECT * FROM fraud_decisions", registry=reg)
