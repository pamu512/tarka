import type { InferenceContext } from "../../api/inferenceContext";

export type SaarthiFeatureImportanceRequestBody = {
  trace_id: string;
  tenant_id: string;
  entity_id: string;
  risk_score: number;
  decision: string;
  inference_context: InferenceContext | null;
  rule_hits: string[];
  tags: string[];
};

export type SaarthiFeatureImportanceItem = {
  signal_id: string;
  label: string;
  /** Relative weight 0–100 (sums to ~100 across items). */
  importance: number;
  category?: string;
};

export type SaarthiFeatureImportanceResponse = {
  items: SaarthiFeatureImportanceItem[];
  lead_rationale: string;
  attribution_engine: "mock" | "gemini" | "heuristic";
};

type RawSignal = { signal_id: string; label: string; category: string; weight: number };

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(1, n));
}

function pushSignal(out: RawSignal[], seen: Set<string>, row: RawSignal): void {
  if (seen.has(row.signal_id)) return;
  seen.add(row.signal_id);
  out.push(row);
}

/** Deterministic driver ranking from audit inference (mock + heuristic fallback). */
export function rankFeatureImportanceFromAudit(
  body: SaarthiFeatureImportanceRequestBody,
): SaarthiFeatureImportanceResponse {
  const ctx = body.inference_context;
  const raw: RawSignal[] = [];
  const seen = new Set<string>();

  if (ctx) {
    for (const d of ctx.driver_explain ?? []) {
      pushSignal(raw, seen, {
        signal_id: `driver:${d.reason}`,
        label: d.label,
        category: d.category,
        weight:
          0.55 +
          clamp01(ctx.graph_risk_score) * 0.1 +
          (d.category === "velocity" ? 0.12 : d.category === "integrity" ? 0.1 : 0.05),
      });
    }
    for (const f of ctx.ml_top_factors ?? []) {
      pushSignal(raw, seen, {
        signal_id: `ml:${f.code}`,
        label: f.description || f.code,
        category: "ml",
        weight: 0.35 + (f.impact?.toLowerCase().includes("high") ? 0.2 : 0.08),
      });
    }
    for (const s of ctx.top_signals ?? []) {
      pushSignal(raw, seen, {
        signal_id: `signal:${s}`,
        label: s.replace(/_/g, " "),
        category: "signal",
        weight: 0.28,
      });
    }
    pushSignal(raw, seen, {
      signal_id: "metric:velocity_24h",
      label: `Velocity burst (${ctx.velocity_events_24h} events / 24h)`,
      category: "velocity",
      weight: 0.2 + Math.min(0.45, ctx.velocity_events_24h / 80),
    });
    pushSignal(raw, seen, {
      signal_id: "metric:graph_risk",
      label: `Graph linkage risk (${(clamp01(ctx.graph_risk_score) * 100).toFixed(0)}%)`,
      category: "graph",
      weight: 0.18 + clamp01(ctx.graph_risk_score) * 0.42,
    });
    pushSignal(raw, seen, {
      signal_id: "metric:network_trust",
      label: `Network trust (${(clamp01(ctx.network_trust) * 100).toFixed(0)}%)`,
      category: "integrity",
      weight: 0.12 + (1 - clamp01(ctx.network_trust)) * 0.35,
    });
    pushSignal(raw, seen, {
      signal_id: "metric:tamper_risk",
      label: `Device tamper risk (${(clamp01(ctx.tamper_risk) * 100).toFixed(0)}%)`,
      category: "integrity",
      weight: 0.1 + clamp01(ctx.tamper_risk) * 0.38,
    });
    pushSignal(raw, seen, {
      signal_id: "metric:geo_consistency",
      label: `Geo consistency risk (${(clamp01(ctx.geo_consistency_risk) * 100).toFixed(0)}%)`,
      category: "geo",
      weight: 0.1 + clamp01(ctx.geo_consistency_risk) * 0.32,
    });
    pushSignal(raw, seen, {
      signal_id: "metric:impossible_travel",
      label: `Impossible travel (${(clamp01(ctx.impossible_travel_risk) * 100).toFixed(0)}%)`,
      category: "geo",
      weight: 0.08 + clamp01(ctx.impossible_travel_risk) * 0.4,
    });
    if (ctx.external_signal_score > 0) {
      pushSignal(raw, seen, {
        signal_id: "metric:external_osint",
        label: `External OSINT score (${ctx.external_signal_score})`,
        category: "osint",
        weight: 0.14 + Math.min(0.3, ctx.external_signal_score / 100),
      });
    }
  }

  for (const hit of body.rule_hits ?? []) {
    const id = String(hit).trim();
    if (!id) continue;
    pushSignal(raw, seen, {
      signal_id: `rule:${id}`,
      label: `Rule fired: ${id}`,
      category: "policy",
      weight: 0.42,
    });
  }

  if (raw.length === 0) {
    pushSignal(raw, seen, {
      signal_id: "score:baseline",
      label: `Baseline model score (${body.risk_score.toFixed(1)}/100)`,
      category: "model",
      weight: 1,
    });
  }

  raw.sort((a, b) => b.weight - a.weight);
  const top = raw.slice(0, 8);
  const sumW = top.reduce((s, r) => s + r.weight, 0) || 1;
  const items: SaarthiFeatureImportanceItem[] = top.map((r) => ({
    signal_id: r.signal_id,
    label: r.label,
    category: r.category,
    importance: Math.round((r.weight / sumW) * 1000) / 10,
  }));

  const lead = items[0];
  const leadLabel = lead?.label ?? "composite risk";
  const lead_rationale =
    items.length > 0
      ? `Saarthi ranks **${leadLabel}** as the strongest explanatory driver for this ${body.decision} at ${body.risk_score.toFixed(1)}/100 — use the chart for relative weighting across velocity, graph, integrity, and policy signals.`
      : `Insufficient structured drivers on the audit to rank feature importance for trace ${body.trace_id}.`;

  return {
    items,
    lead_rationale,
    attribution_engine: "heuristic",
  };
}

export function buildSaarthiFeatureImportanceRequest(params: {
  traceId: string;
  tenantId: string;
  entityId: string;
  score: number;
  decision: string;
  inference: InferenceContext | null;
  ruleHits: string[];
  tags: string[];
}): SaarthiFeatureImportanceRequestBody {
  return {
    trace_id: params.traceId,
    tenant_id: params.tenantId,
    entity_id: params.entityId,
    risk_score: params.score,
    decision: params.decision,
    inference_context: params.inference,
    rule_hits: params.ruleHits,
    tags: params.tags,
  };
}
