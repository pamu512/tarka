/**
 * Case-api mock slice — start of mockData.ts shrink for `/api/cases/v1/*`.
 * Evidence + health first; list/CRUD/disputes remain in mockData.ts until a later cut.
 */

export function getCasesMockResponse(args: {
  url: string;
  path: string;
  method: string;
  body: Record<string, unknown>;
}): unknown | null {
  const { path } = args;

  if (path.includes("/api/cases/v1/health")) {
    return {
      status: "ok",
      database_backend: "postgresql",
      database_url: "postgresql+asyncpg://fraud:***@localhost:5432/fraud_cases",
      database_fallback_active: false,
      database_fallback_reason: null,
      database_bootstrap_mode: "alembic_head",
    };
  }

  if (path.includes("/evidence-bundle") && !path.includes(".zip")) {
    return {
      bundle_version: "1",
      tenant_id: "demo",
      case: {
        id: "case-demo",
        tenant_id: "demo",
        entity_id: "entity-demo",
        title: "Demo case",
        trace_id: "tr-demo",
      },
      decision_audit: {
        trace_id: "tr-demo",
        decision: "review",
        score: 74,
        recommended_action: "manual_review",
      },
      evidence_bundle_v1: {
        schema_id: "tarka.evidence_bundle/v1",
        content_sha256: "mocksha256",
      },
      bundle_signature: "mock",
      signing_key_id: "mock",
    };
  }

  return null;
}
