"""PLG sandbox bootstrap — industry rule templates into Postgres + live Rust engine."""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from decision_api.deps import get_pg_pool
from decision_api.json_rules import preload_plg_sandbox_runtime_pack, set_plg_sandbox_runtime_pack
from decision_api.sandbox_plg_pack import PLG_BUNDLE_KEY, build_merged_plg_industry_pack, merged_pack_fingerprint
from tarka_core.templates import list_industry_template_items

log = logging.getLogger("decision-api")

router = APIRouter(prefix="/v1/sandbox", tags=["sandbox"])


class SandboxBootstrapResponse(BaseModel):
    status: str = Field(default="ok")
    bundle_key: str
    template_keys: list[str]
    merged_rule_count: int
    merged_tag_rule_count: int
    merged_pack_fingerprint_sha256: str
    rule_approval_inserted: bool
    idempotent: bool = Field(
        default=True,
        description="Bootstrap uses upserts; repeated calls do not raise duplicate-key errors.",
    )


async def _require_api_key(request: Request) -> None:
    from decision_api import main as main_mod

    await main_mod.require_api_key(request)


async def maybe_hydrate_sandbox_plg_pack(application: Any) -> None:
    """Load merged PLG pack from Postgres before the first ``load_rules()`` (best-effort)."""
    pool = getattr(application.state, "pg_pool", None)
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT merged_pack_json
                FROM sandbox_plg_bundle_state
                WHERE bundle_key = $1
                """,
                PLG_BUNDLE_KEY,
            )
    except Exception as e:
        log.warning("sandbox PLG hydrate skipped (missing migration or DB): %s", e)
        return
    if row and row["merged_pack_json"]:
        preload_plg_sandbox_runtime_pack(dict(row["merged_pack_json"]))


@router.post("/bootstrap", response_model=SandboxBootstrapResponse)
async def sandbox_bootstrap(
    request: Request,
    pool: Any = Depends(get_pg_pool),
    _auth: None = Depends(_require_api_key),
) -> SandboxBootstrapResponse:
    """Idempotently install five industry templates into the audit tables and the Rust engine."""
    import asyncpg

    try:
        merged, per_compiled, template_keys = build_merged_plg_industry_pack()
    except ValueError as e:
        raise HTTPException(status_code=500, detail={"reason_code": "SANDBOOT_COMPILE_FAILED", "message": str(e)}) from e

    fp = merged_pack_fingerprint(merged)
    rule_approval_inserted = False

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for template_key, ast in list_industry_template_items():
                    compiled = per_compiled[template_key]
                    rules_only = compiled.get("rules") or []
                    await conn.execute(
                        """
                        INSERT INTO sandbox_industry_rule_templates (
                            id, template_key, bundle_key, approval_status,
                            visual_ast_pack, compiled_rules, merged_pack_fingerprint_sha256
                        )
                        VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
                        ON CONFLICT ON CONSTRAINT uq_sandbox_industry_templates_key_bundle
                        DO UPDATE SET
                            approval_status = EXCLUDED.approval_status,
                            visual_ast_pack = EXCLUDED.visual_ast_pack,
                            compiled_rules = EXCLUDED.compiled_rules,
                            merged_pack_fingerprint_sha256 = EXCLUDED.merged_pack_fingerprint_sha256,
                            updated_at = now()
                        """,
                        uuid.uuid4(),
                        template_key,
                        PLG_BUNDLE_KEY,
                        "APPROVED",
                        json.dumps(ast),
                        json.dumps(rules_only),
                        fp,
                    )

                await conn.execute(
                    """
                    INSERT INTO sandbox_plg_bundle_state (bundle_key, merged_pack_json, fingerprint_sha256, updated_at)
                    VALUES ($1, $2::jsonb, $3, now())
                    ON CONFLICT (bundle_key) DO UPDATE SET
                        merged_pack_json = EXCLUDED.merged_pack_json,
                        fingerprint_sha256 = EXCLUDED.fingerprint_sha256,
                        updated_at = now()
                    """,
                    PLG_BUNDLE_KEY,
                    json.dumps(merged),
                    fp,
                )

                exists = await conn.fetchval(
                    """
                    SELECT 1 FROM rule_approvals
                    WHERE pack_name = $1 AND fingerprint_sha256 = $2
                    LIMIT 1
                    """,
                    "sandbox_plg_industry_bundle",
                    fp,
                )
                if not exists:
                    await conn.execute(
                        """
                        INSERT INTO rule_approvals (
                            id, pack_name, fingerprint_sha256, actor_user_id, audit_token, created_at
                        )
                        VALUES ($1::uuid, $2, $3, $4, $5, now())
                        """,
                        uuid.uuid4(),
                        "sandbox_plg_industry_bundle",
                        fp,
                        "sandbox_bootstrap",
                        secrets.token_urlsafe(32),
                    )
                    rule_approval_inserted = True
    except asyncpg.UndefinedTableError as e:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "SANDBOOT_MIGRATION_REQUIRED",
                "message": "Run Alembic migrations for decision-api (sandbox_industry_rule_templates).",
            },
        ) from e
    except Exception as e:
        log.exception("sandbox bootstrap failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={"reason_code": "SANDBOOT_PERSISTENCE_FAILED", "message": str(e)},
        ) from e

    set_plg_sandbox_runtime_pack(merged)

    return SandboxBootstrapResponse(
        bundle_key=PLG_BUNDLE_KEY,
        template_keys=template_keys,
        merged_rule_count=len(merged.get("rules") or []),
        merged_tag_rule_count=len(merged.get("tag_rules") or []),
        merged_pack_fingerprint_sha256=fp,
        rule_approval_inserted=rule_approval_inserted,
    )
