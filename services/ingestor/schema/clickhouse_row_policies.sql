-- =============================================================================
-- Row-Level Security (tenant isolation) for `tarka_audit` tables
-- =============================================================================
-- Apply after tables exist (see clickhouse.sql). Queries using restricted roles must
-- satisfy row policies on SELECT.
--
-- Session-scoped tenant (recommended for internal tools sharing one ClickHouse user):
--   1. Server config must allow custom settings, e.g.:
--        <custom_settings_prefixes>
--            <prefix>tarka_</prefix>
--        </custom_settings_prefixes>
--   2. Before SELECT, clients run (HTTP/SQL): SET tarka_tenant_id = 'environment-a';
--      clickhouse-connect: client.query(..., settings={"tarka_tenant_id": "environment-a"})
--
-- Without SET, SELECT returns no rows when the policy compares tenant_id to an unset setting
-- (operators should grant SELECT only to roles bound by these policies).
--
-- Ingest / MV writers: use a dedicated technical user with INSERT rights; row policies below
-- target SELECT on analyst/query roles only (`tarka_query`). Adjust GRANTs to your RBAC model.
-- =============================================================================

CREATE ROLE IF NOT EXISTS tarka_query;

-- Evidence manifests: only rows for the active session tenant are visible to `tarka_query`.
CREATE ROW POLICY IF NOT EXISTS rls_evidence_manifests_select ON tarka_audit.evidence_manifests
    FOR SELECT USING tenant_id = getSetting('tarka_tenant_id')
    TO tarka_query;

CREATE ROW POLICY IF NOT EXISTS rls_evidence_manifest_decisions_select ON tarka_audit.evidence_manifest_decisions
    FOR SELECT USING tenant_id = getSetting('tarka_tenant_id')
    TO tarka_query;

CREATE ROW POLICY IF NOT EXISTS rls_audit_anchors_select ON tarka_audit.audit_anchors
    FOR SELECT USING tenant_id = getSetting('tarka_tenant_id')
    TO tarka_query;

CREATE ROW POLICY IF NOT EXISTS rls_mv_day_agg_select ON tarka_audit.mv_decision_consistency_by_input_agg
    FOR SELECT USING tenant_id = getSetting('tarka_tenant_id')
    TO tarka_query;

CREATE ROW POLICY IF NOT EXISTS rls_mv_hour_agg_select ON tarka_audit.mv_decision_consistency_by_hour_agg
    FOR SELECT USING tenant_id = getSetting('tarka_tenant_id')
    TO tarka_query;

-- Example: analyst principal (repeat per environment or map SSO groups → roles).
-- GRANT tarka_query TO analyst_env_a;
-- GRANT SELECT ON tarka_audit.evidence_manifests TO analyst_env_a;
