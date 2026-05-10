import type { AuditEntry } from "@/api/client";
import { normalizeInferenceContext } from "@/api/inferenceContext";

export type ThoughtTraceStep = {
  id: string;
  heading: string;
  body: string;
  /** Step-specific confidence weight in ``0..1``. */
  weight: number;
};

function impactToWeight(impact: string): number {
  const i = impact.toLowerCase();
  if (i === "high") return 0.88;
  if (i === "medium" || i === "med") return 0.62;
  if (i === "low") return 0.38;
  return 0.52;
}

/**
 * Builds ordered Shadow-AI-style thought steps from persisted audit explainability.
 * Prefer ``explanation_drivers`` (ranked); otherwise driver explain + ML factors + summary.
 */
export function buildShadowThoughtTrace(audit: AuditEntry): ThoughtTraceStep[] {
  const steps: ThoughtTraceStep[] = [];
  const drivers = audit.explanation_drivers;
  if (Array.isArray(drivers) && drivers.length > 0) {
    const sorted = [...drivers].sort((a, b) => a.rank - b.rank);
    const maxRank = Math.max(...sorted.map((d) => d.rank), 1);
    for (const d of sorted) {
      const spread = maxRank > 1 ? (maxRank - d.rank) / (maxRank - 1) : 1;
      const weight = Math.min(0.98, 0.35 + spread * 0.6);
      steps.push({
        id: `driver-${d.rank}-${d.reason}`,
        heading: d.label || d.category,
        body: d.reason,
        weight,
      });
    }
    const infAfterDrivers = normalizeInferenceContext(audit.inference_context);
    if (infAfterDrivers) {
      for (const mf of infAfterDrivers.ml_top_factors) {
        steps.push({
          id: `ml-${mf.code}`,
          heading: mf.code,
          body: mf.description,
          weight: impactToWeight(mf.impact),
        });
      }
    }
    return steps;
  }

  const inf = normalizeInferenceContext(audit.inference_context);
  if (!inf) return steps;

  const nEx = inf.driver_explain.length;
  inf.driver_explain.forEach((de, i) => {
    const spread = nEx > 1 ? (nEx - 1 - i) / (nEx - 1) : 1;
    const base = typeof inf.integrity_confidence === "number" ? inf.integrity_confidence : 0.55;
    const weight = Math.min(0.98, Math.max(0.06, base * (0.45 + spread * 0.55)));
    steps.push({
      id: `explain-${i}-${de.reason}`,
      heading: `${de.category}: ${de.label}`.slice(0, 160),
      body: de.reason,
      weight,
    });
  });

  for (const mf of inf.ml_top_factors) {
    steps.push({
      id: `ml-${mf.code}`,
      heading: mf.code,
      body: mf.description,
      weight: impactToWeight(mf.impact),
    });
  }

  if (steps.length === 0 && inf.ml_summary && inf.ml_summary.trim().length > 0) {
    const base = typeof inf.integrity_confidence === "number" ? inf.integrity_confidence : 0.55;
    steps.push({
      id: "ml-summary",
      heading: "Model summary",
      body: inf.ml_summary,
      weight: Math.min(0.98, Math.max(0.12, base)),
    });
  }

  return steps;
}

/** True when no Shadow-AI narrative exists (e.g. hard rule path / engine bypass). */
export function isDeterministicAiBypass(audit: AuditEntry, steps: ThoughtTraceStep[]): boolean {
  return steps.length === 0;
}
