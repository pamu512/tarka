"""PostgreSQL schema for the Triple-DB stack using ``pulumi_postgresql``.

The upstream Terraform PostgreSQL provider (and thus ``pulumi_postgresql`` v3) does not expose a
``Table`` resource. We model DDL with a one-shot ``postgresql.Function`` (``plpgsql``) whose body
runs idempotent ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS`` statements, plus
``postgresql.Extension`` for ``pgcrypto`` so ``gen_random_uuid()`` is available on older servers.
A ``pulumi_command.local.Command`` runs ``psql`` once to invoke that function (DDL is not executed
at CREATE FUNCTION time in PostgreSQL).

Requires stack secret ``triple-db:postgresPassword`` (``pulumi config set --secret ...``).
"""

from __future__ import annotations

import pulumi
import pulumi_postgresql as pg
from pulumi_command import local

# Idempotent DDL: safe to re-run on every update.
_BOOTSTRAP_FN_BODY = r"""
BEGIN
  CREATE TABLE IF NOT EXISTS public.rule_sets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(255) NOT NULL,
    description text,
    created_at timestamptz NOT NULL DEFAULT now()
  );

  CREATE TABLE IF NOT EXISTS public.rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_set_id uuid NOT NULL REFERENCES public.rule_sets (id) ON DELETE CASCADE,
    rule_hash varchar(64) NOT NULL,
    name varchar(255) NOT NULL,
    definition jsonb NOT NULL DEFAULT '{}'::jsonb,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_rules_rule_set_hash_version UNIQUE (rule_set_id, rule_hash, version)
  );

  CREATE INDEX IF NOT EXISTS ix_rules_rule_hash ON public.rules (rule_hash);

  CREATE TABLE IF NOT EXISTS public.audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_hash varchar(64),
    actor varchar(256) NOT NULL,
    action varchar(128) NOT NULL,
    resource_type varchar(64),
    resource_id varchar(256),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
  );

  CREATE INDEX IF NOT EXISTS ix_audit_log_rule_hash ON public.audit_log (rule_hash);
END;
"""


def provision(*, cfg: pulumi.Config | None = None) -> None:
    """Create provider, ensure ``pgcrypto``, and apply the bootstrap function (DDL)."""
    cfg = cfg or pulumi.Config()
    db = cfg.require("postgresDatabase")
    sslmode = cfg.get("postgresSslmode") or "prefer"
    superuser_raw = cfg.get("postgresSuperuser")
    if superuser_raw is None:
        connect_as_superuser = True
    else:
        connect_as_superuser = cfg.get_bool("postgresSuperuser")

    provider = pg.Provider(
        "triple-db-postgres",
        host=cfg.require("postgresHost"),
        port=cfg.require_int("postgresPort"),
        username=cfg.require("postgresUser"),
        password=cfg.require_secret("postgresPassword"),
        database=db,
        sslmode=sslmode,
        connect_timeout=30,
        superuser=connect_as_superuser,
    )

    pgcrypto = pg.Extension(
        "triple-db-pgcrypto",
        name="pgcrypto",
        database=db,
        opts=pulumi.ResourceOptions(provider=provider),
    )

    bootstrap_fn = pg.Function(
        "triple-db-bootstrap-schema",
        database=db,
        schema="public",
        name="fn_triple_db_bootstrap_schema",
        language="plpgsql",
        returns="void",
        volatility="VOLATILE",
        parallel="UNSAFE",
        body=_BOOTSTRAP_FN_BODY,
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[pgcrypto]),
    )

    create_sql = pulumi.Output.all(
        cfg.require("postgresHost"),
        cfg.require_int("postgresPort"),
        cfg.require("postgresUser"),
        cfg.require("postgresDatabase"),
    ).apply(
        lambda parts: (
            "psql "
            f"-h {parts[0]} -p {parts[1]} -U {parts[2]} -d {parts[3]} "
            '-v ON_ERROR_STOP=1 -c "SELECT public.fn_triple_db_bootstrap_schema();"'
        )
    )
    delete_sql = pulumi.Output.all(
        cfg.require("postgresHost"),
        cfg.require_int("postgresPort"),
        cfg.require("postgresUser"),
        cfg.require("postgresDatabase"),
    ).apply(
        lambda parts: (
            "psql "
            f"-h {parts[0]} -p {parts[1]} -U {parts[2]} -d {parts[3]} "
            '-v ON_ERROR_STOP=1 -c "DROP FUNCTION IF EXISTS public.fn_triple_db_bootstrap_schema() CASCADE;"'
        )
    )
    pg_env = pulumi.Output.all(cfg.require_secret("postgresPassword")).apply(
        lambda parts: {"PGPASSWORD": parts[0]}
    )

    local.Command(
        "triple-db-exec-bootstrap",
        create=create_sql,
        delete=delete_sql,
        environment=pg_env,
        triggers=[_BOOTSTRAP_FN_BODY],
        opts=pulumi.ResourceOptions(depends_on=[bootstrap_fn]),
    )
