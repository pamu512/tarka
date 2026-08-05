/**
 * Case-api mock slice for `/api/cases/v1/*` desk ops (missed-mark bridge A2).
 * Used only when VITE_USE_API_MOCKS=true (desk-strict blocks auto fallback).
 */

export function getCasesMockResponse(args: {
  url: string;
  path: string;
  method: string;
  body: Record<string, unknown>;
}): unknown | null {
  const { path, method, body } = args;
  const nowIso = () => new Date().toISOString();

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

  if (path.includes("/api/cases/v1/cases/ops/kpis")) {
    return {
      tenant_id: "demo",
      total_cases: 4,
      queue_score_avg: 85,
      critical_open: 1,
      investigating_rate: 0.4,
      resolved_rate: 0.2,
      median_case_age_hours: 6.5,
      by_status: { open: 2, investigating: 1, closed: 1 },
      sla_breached_open_or_investigating: 0,
      label_boost_cases: 1,
    };
  }

  if (path.includes("/api/cases/v1/cases/ops/desk-activity")) {
    return {
      tenant_id: "demo",
      period_days: 7,
      since: new Date(Date.now() - 7 * 86400000).toISOString(),
      touch_actions_total: 4,
      by_action: { update_case: 2, add_comment: 1, update_labels: 1 },
      recent: [
        {
          id: "a1",
          action: "update_case",
          actor: "analyst@demo",
          resource_id: "c1",
          created_at: nowIso(),
        },
      ],
    };
  }

  if (path.includes("/api/cases/v1/cases/ops/qa-sample")) {
    return {
      tenant_id: "demo",
      rate: 0.1,
      seed: "mock",
      candidates: 2,
      sampled: 1,
      queued: ["c1"],
    };
  }

  if (path.includes("/api/cases/v1/cases/ops/qa-review")) {
    return {
      case_id: String(body?.case_id ?? "c1"),
      original_status: String(body?.original_status ?? "resolved"),
      qa_status: String(body?.qa_status ?? "resolved"),
      agree:
        String(body?.qa_status ?? "resolved") ===
        String(body?.original_status ?? "resolved"),
    };
  }

  if (path.includes("/api/cases/v1/cases/ops/qa-metrics")) {
    return {
      tenant_id: "demo",
      pending: 1,
      reviewed: 2,
      agree: 1,
      disagree: 1,
      agreement_rate: 0.5,
      disagreement_rate: 0.5,
    };
  }

  if (path.includes("/api/cases/v1/cases/analytics/cohort-compare")) {
    return {
      tenant_id: "demo",
      period_days: 7,
      cases_created_recent: 12,
      cases_created_prior: 10,
      delta: 2,
      delta_percent_vs_prior: 20,
      status_mix_recent: { open: 7, investigating: 3, closed: 2 },
      status_mix_prior: { open: 5, investigating: 3, closed: 2 },
      priority_mix_recent: { high: 4, medium: 6, low: 2 },
      priority_mix_prior: { high: 3, medium: 5, low: 2 },
    };
  }

  if (path.includes("/api/cases/v1/cases/playbooks")) {
    return {
      playbooks: {
        escalate: { label: "Escalate", target_status: "investigating" },
        close_fp: { label: "Close False Positive", target_status: "closed" },
      },
    };
  }

  if (path.includes("/api/cases/v1/case-views")) {
    if (method === "GET") {
      return { items: [{ name: "High Risk", tenant_id: "demo", filters: { priority: "high" } }] };
    }
    if (method === "POST") return { ok: true, view: { name: body.name ?? "Saved View" } };
    if (method === "DELETE") return { removed: true };
  }

  return null;
}
