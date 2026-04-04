/**
 * Aligned with `components/schemas/InferenceContext` in `contracts/openapi/decision-api.yaml`.
 * Evaluate responses require the full object; audit rows may return partial JSON — use `normalizeInferenceContext`.
 */
export type ConfidenceTier = "low" | "medium" | "high";

export interface InferenceContext {
  schema_version: string;
  integrity_confidence: number;
  tamper_risk: number;
  network_trust: number;
  replay_risk: number;
  geo_consistency_risk: number;
  top_signals: string[];
  confidence_tier: ConfidenceTier;
  driver_reasons: string[];
  colocation_risk: number;
  impossible_travel_risk: number;
  velocity_events_5m: number;
  velocity_events_1h: number;
  velocity_events_24h: number;
}

/** Lenient audit / gateway payload before normalization. */
export type InferenceContextLike = Partial<InferenceContext>;

function asConfidenceTier(v: unknown): ConfidenceTier {
  return v === "low" || v === "medium" || v === "high" ? v : "medium";
}

/** Coerces partial or unknown JSON into a full `InferenceContext` for safe UI rendering. */
export function normalizeInferenceContext(raw: unknown): InferenceContext | null {
  if (raw == null || typeof raw !== "object") return null;
  const r = raw as InferenceContextLike;
  return {
    schema_version: typeof r.schema_version === "string" ? r.schema_version : "2",
    integrity_confidence: typeof r.integrity_confidence === "number" ? r.integrity_confidence : 0,
    tamper_risk: typeof r.tamper_risk === "number" ? r.tamper_risk : 0,
    network_trust: typeof r.network_trust === "number" ? r.network_trust : 0,
    replay_risk: typeof r.replay_risk === "number" ? r.replay_risk : 0,
    geo_consistency_risk: typeof r.geo_consistency_risk === "number" ? r.geo_consistency_risk : 0,
    top_signals: Array.isArray(r.top_signals) ? r.top_signals.filter((s): s is string => typeof s === "string") : [],
    confidence_tier: asConfidenceTier(r.confidence_tier),
    driver_reasons: Array.isArray(r.driver_reasons)
      ? r.driver_reasons.filter((s): s is string => typeof s === "string")
      : [],
    colocation_risk: typeof r.colocation_risk === "number" ? r.colocation_risk : 0,
    impossible_travel_risk: typeof r.impossible_travel_risk === "number" ? r.impossible_travel_risk : 0,
    velocity_events_5m: typeof r.velocity_events_5m === "number" ? r.velocity_events_5m : 0,
    velocity_events_1h: typeof r.velocity_events_1h === "number" ? r.velocity_events_1h : 0,
    velocity_events_24h: typeof r.velocity_events_24h === "number" ? r.velocity_events_24h : 0,
  };
}
