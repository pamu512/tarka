/**
 * Aligned with `components/schemas/InferenceContext` in `contracts/openapi/decision-api.yaml`.
 * Evaluate responses require the full object; audit rows may return partial JSON — use `normalizeInferenceContext`.
 */
export type ConfidenceTier = "low" | "medium" | "high";

export interface MlTopFactor {
  code: string;
  description: string;
  impact: string;
}

export interface DriverExplainEntry {
  reason: string;
  category: string;
  label: string;
}

export interface InferenceContext {
  schema_version: string;
  calibration_profile: string;
  expected_calibration_version: number;
  calibration_profile_version: number;
  location_confidence: number;
  confidence_sources: {
    calibration: string;
    counter: string;
    location: string;
  };
  graph_risk_score: number;
  graph_risk_reasons: string[];
  external_signal_score: number;
  external_signal_providers: string[];
  policy_experiment_id: string | null;
  confidence_tier_label: string;
  driver_explain: DriverExplainEntry[];
  integrity_confidence: number;
  tamper_risk: number;
  network_trust: number;
  replay_risk: number;
  geo_consistency_risk: number;
  top_signals: string[];
  confidence_tier: ConfidenceTier;
  driver_reasons: string[];
  colocation_risk: number;
  copresence_risk: number;
  impossible_travel_risk: number;
  velocity_events_5m: number;
  velocity_events_1h: number;
  velocity_events_24h: number;
  /** Optional UTC histogram from decision-api / analytics (24 entries, hour 0 = 00:00 UTC). */
  velocity_events_by_hour_utc?: number[] | null;
  ml_top_factors: MlTopFactor[];
  ml_summary: string | null;
  ml_model: string | null;
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
  const rawExplain = r.driver_explain;
  const driverExplainRaw: unknown[] = Array.isArray(rawExplain) ? rawExplain : [];
  const driver_explain: DriverExplainEntry[] = driverExplainRaw
    .filter(
      (x): x is DriverExplainEntry =>
        x != null &&
        typeof x === "object" &&
        typeof (x as DriverExplainEntry).reason === "string" &&
        typeof (x as DriverExplainEntry).category === "string" &&
        typeof (x as DriverExplainEntry).label === "string",
    )
    .map((x) => ({
      reason: x.reason,
      category: x.category,
      label: x.label,
    }));

  return {
    schema_version: typeof r.schema_version === "string" ? r.schema_version : "3",
    calibration_profile: typeof r.calibration_profile === "string" ? r.calibration_profile : "default",
    expected_calibration_version: typeof r.expected_calibration_version === "number" ? r.expected_calibration_version : 1,
    calibration_profile_version: typeof (r as { calibration_profile_version?: unknown }).calibration_profile_version === "number"
      ? ((r as { calibration_profile_version: number }).calibration_profile_version ?? 1)
      : 1,
    location_confidence: typeof (r as { location_confidence?: unknown }).location_confidence === "number"
      ? ((r as { location_confidence: number }).location_confidence ?? 0)
      : 0,
    confidence_sources:
      (r as { confidence_sources?: unknown }).confidence_sources &&
      typeof (r as { confidence_sources?: unknown }).confidence_sources === "object"
        ? {
            calibration:
              typeof ((r as { confidence_sources?: { calibration?: unknown } }).confidence_sources?.calibration) === "string"
                ? ((r as { confidence_sources?: { calibration?: string } }).confidence_sources?.calibration ?? "heuristic")
                : "heuristic",
            counter:
              typeof ((r as { confidence_sources?: { counter?: unknown } }).confidence_sources?.counter) === "string"
                ? ((r as { confidence_sources?: { counter?: string } }).confidence_sources?.counter ?? "heuristic")
                : "heuristic",
            location:
              typeof ((r as { confidence_sources?: { location?: unknown } }).confidence_sources?.location) === "string"
                ? ((r as { confidence_sources?: { location?: string } }).confidence_sources?.location ?? "heuristic")
                : "heuristic",
          }
        : {
            calibration: "heuristic",
            counter: "heuristic",
            location: "heuristic",
          },
    confidence_tier_label: (() => {
      if (typeof (r as InferenceContextLike).confidence_tier_label === "string") {
        return (r as InferenceContextLike).confidence_tier_label as string;
      }
      const t = asConfidenceTier(r.confidence_tier);
      return t === "high"
        ? "High — integrity signals support confident scoring"
        : t === "low"
          ? "Low — weak integrity or conflicting signals"
          : "Medium — mixed signals; review edge cases";
    })(),
    driver_explain,
    integrity_confidence: typeof r.integrity_confidence === "number" ? r.integrity_confidence : 0,
    tamper_risk: typeof r.tamper_risk === "number" ? r.tamper_risk : 0,
    network_trust: typeof r.network_trust === "number" ? r.network_trust : 0,
    replay_risk: typeof r.replay_risk === "number" ? r.replay_risk : 0,
    geo_consistency_risk: typeof r.geo_consistency_risk === "number" ? r.geo_consistency_risk : 0,
    top_signals: Array.isArray(r.top_signals) ? r.top_signals.filter((s): s is string => typeof s === "string") : [],
    confidence_tier: asConfidenceTier(r.confidence_tier),
    graph_risk_score:
      typeof (r as { graph_risk_score?: unknown }).graph_risk_score === "number"
        ? ((r as { graph_risk_score: number }).graph_risk_score ?? 0)
        : 0,
    graph_risk_reasons:
      Array.isArray((r as { graph_risk_reasons?: unknown }).graph_risk_reasons)
        ? ((r as { graph_risk_reasons: unknown[] }).graph_risk_reasons ?? []).filter((x): x is string => typeof x === "string")
        : [],
    external_signal_score:
      typeof (r as { external_signal_score?: unknown }).external_signal_score === "number"
        ? ((r as { external_signal_score: number }).external_signal_score ?? 0)
        : 0,
    external_signal_providers:
      Array.isArray((r as { external_signal_providers?: unknown }).external_signal_providers)
        ? ((r as { external_signal_providers: unknown[] }).external_signal_providers ?? []).filter((x): x is string => typeof x === "string")
        : [],
    policy_experiment_id:
      typeof (r as { policy_experiment_id?: unknown }).policy_experiment_id === "string"
        ? ((r as { policy_experiment_id: string }).policy_experiment_id ?? null)
        : null,
    driver_reasons: Array.isArray(r.driver_reasons)
      ? r.driver_reasons.filter((s): s is string => typeof s === "string")
      : [],
    colocation_risk: typeof r.colocation_risk === "number" ? r.colocation_risk : 0,
    copresence_risk:
      typeof r.copresence_risk === "number"
        ? r.copresence_risk
        : typeof r.colocation_risk === "number"
          ? r.colocation_risk
          : 0,
    impossible_travel_risk: typeof r.impossible_travel_risk === "number" ? r.impossible_travel_risk : 0,
    velocity_events_5m: typeof r.velocity_events_5m === "number" ? r.velocity_events_5m : 0,
    velocity_events_1h: typeof r.velocity_events_1h === "number" ? r.velocity_events_1h : 0,
    velocity_events_24h: typeof r.velocity_events_24h === "number" ? r.velocity_events_24h : 0,
    velocity_events_by_hour_utc: (() => {
      const h = (r as { velocity_events_by_hour_utc?: unknown }).velocity_events_by_hour_utc;
      if (!Array.isArray(h) || h.length !== 24) return undefined;
      const nums = h.map((x) =>
        typeof x === "number" && Number.isFinite(x) ? Math.max(0, Math.round(x)) : 0,
      );
      return nums;
    })(),
    ml_top_factors: Array.isArray(r.ml_top_factors)
      ? r.ml_top_factors.filter(
          (x): x is MlTopFactor =>
            x != null &&
            typeof x === "object" &&
            typeof (x as MlTopFactor).code === "string" &&
            typeof (x as MlTopFactor).description === "string" &&
            typeof (x as MlTopFactor).impact === "string",
        )
      : [],
    ml_summary: typeof r.ml_summary === "string" ? r.ml_summary : null,
    ml_model: typeof r.ml_model === "string" ? r.ml_model : null,
  };
}
