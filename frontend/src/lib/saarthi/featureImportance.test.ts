import { describe, expect, it } from "vitest";

import type { InferenceContext } from "../../api/inferenceContext";
import { rankFeatureImportanceFromAudit } from "./featureImportance";

function minimalCtx(overrides: Partial<InferenceContext> = {}): InferenceContext {
  return {
    schema_version: "1",
    calibration_profile: "default",
    expected_calibration_version: 1,
    calibration_profile_version: 1,
    location_confidence: 0.5,
    confidence_sources: { calibration: "ok", counter: "ok", location: "ok" },
    graph_risk_score: 0.7,
    graph_risk_reasons: [],
    external_signal_score: 0,
    external_signal_providers: [],
    policy_experiment_id: null,
    confidence_tier_label: "medium",
    driver_explain: [{ reason: "velocity_guard", category: "velocity", label: "High velocity window" }],
    integrity_confidence: 0.8,
    tamper_risk: 0.2,
    network_trust: 0.6,
    replay_risk: 0.1,
    geo_consistency_risk: 0.3,
    top_signals: [],
    confidence_tier: "medium",
    driver_reasons: [],
    colocation_risk: 0,
    copresence_risk: 0,
    impossible_travel_risk: 0.1,
    velocity_events_5m: 2,
    velocity_events_1h: 10,
    velocity_events_24h: 40,
    ml_top_factors: [],
    ml_summary: null,
    ml_model: null,
    ...overrides,
  };
}

describe("rankFeatureImportanceFromAudit", () => {
  it("returns normalized importance weights summing near 100", () => {
    const res = rankFeatureImportanceFromAudit({
      trace_id: "tr-1",
      tenant_id: "demo",
      entity_id: "ent-1",
      risk_score: 88,
      decision: "review",
      inference_context: minimalCtx(),
      rule_hits: ["velocity_guard"],
      tags: ["velocity"],
    });
    expect(res.items.length).toBeGreaterThan(0);
    const sum = res.items.reduce((s, i) => s + i.importance, 0);
    expect(sum).toBeGreaterThan(95);
    expect(sum).toBeLessThanOrEqual(100.5);
    expect(res.lead_rationale).toContain("velocity");
  });
});
