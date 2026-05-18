import { describe, expect, it } from "vitest";
import {
  allocateIntegersFromWeights,
  buildVelocityHeatmapModel,
  synthesizeHourlyVelocityBuckets,
  utcHourDistance,
  utcHourFromIso,
} from "./velocityHeatmapModel";
import type { InferenceContext } from "../api/inferenceContext";

const baseInference = (): InferenceContext => ({
  schema_version: "3",
  calibration_profile: "default",
  expected_calibration_version: 1,
  calibration_profile_version: 1,
  location_confidence: 0.7,
  confidence_sources: { calibration: "x", counter: "x", location: "x" },
  graph_risk_score: 0,
  graph_risk_reasons: [],
  external_signal_score: 0,
  external_signal_providers: [],
  policy_experiment_id: null,
  confidence_tier_label: "",
  driver_explain: [],
  integrity_confidence: 0,
  tamper_risk: 0,
  network_trust: 0,
  replay_risk: 0,
  geo_consistency_risk: 0,
  top_signals: [],
  confidence_tier: "medium",
  driver_reasons: [],
  colocation_risk: 0,
  copresence_risk: 0,
  impossible_travel_risk: 0,
  velocity_events_5m: 10,
  velocity_events_1h: 20,
  velocity_events_24h: 100,
  ml_top_factors: [],
  ml_summary: null,
  ml_model: null,
});

describe("utcHourDistance", () => {
  it("wraps around midnight", () => {
    expect(utcHourDistance(23, 0)).toBe(1);
    expect(utcHourDistance(0, 23)).toBe(1);
  });
});

describe("utcHourFromIso", () => {
  it("parses UTC hour", () => {
    expect(utcHourFromIso("2026-03-15T14:30:00.000Z")).toBe(14);
  });
});

describe("allocateIntegersFromWeights", () => {
  it("preserves total mass", () => {
    const w = [1, 2, 3, 4];
    const out = allocateIntegersFromWeights(w, 100);
    expect(out.reduce((a, b) => a + b, 0)).toBe(100);
    expect(out.length).toBe(4);
  });
});

describe("synthesizeHourlyVelocityBuckets", () => {
  it("sums to velocity_events_24h", () => {
    const b = synthesizeHourlyVelocityBuckets(5, 30, 72, 18);
    expect(b.reduce((a, x) => a + x, 0)).toBe(72);
    expect(b.length).toBe(24);
  });

  it("returns zeros when 24h count is zero", () => {
    const b = synthesizeHourlyVelocityBuckets(0, 0, 0, 12);
    expect(b.every((x) => x === 0)).toBe(true);
  });
});

describe("buildVelocityHeatmapModel", () => {
  it("uses API hourly array when present", () => {
    const hourly = Array.from({ length: 24 }, (_, i) => (i === 10 ? 50 : 0));
    const inf = { ...baseInference(), velocity_events_by_hour_utc: hourly };
    const m = buildVelocityHeatmapModel(inf, null);
    expect(m?.synthesized).toBe(false);
    expect(m?.peakHourUtc).toBe(10);
    expect(m?.total).toBe(50);
  });

  it("synthesizes when hourly omitted", () => {
    const inf = baseInference();
    const m = buildVelocityHeatmapModel(inf, "2026-01-01T12:00:00Z");
    expect(m?.synthesized).toBe(true);
    expect(m?.total).toBe(100);
  });
});
