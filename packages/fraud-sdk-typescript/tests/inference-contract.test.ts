import { describe, expect, it } from "vitest";
import type { InferenceContext } from "../src/index.js";

describe("InferenceContext typing", () => {
  it("includes core normalized fields", () => {
    const sample: InferenceContext = {
      schema_version: "3",
      calibration_profile: "default",
      expected_calibration_version: 1,
      integrity_confidence: 0.8,
      tamper_risk: 0.1,
      network_trust: 0.9,
      replay_risk: 0.0,
      geo_consistency_risk: 0.2,
      top_signals: ["sdk:vpn"],
      confidence_tier: "high",
      driver_reasons: ["hostile_or_anonymous_network_path"],
      colocation_risk: 0.0,
      copresence_risk: 0.0,
      impossible_travel_risk: 0.0,
      velocity_events_5m: 1,
      velocity_events_1h: 3,
      velocity_events_24h: 9,
      confidence_tier_label: "High",
      driver_explain: [{ reason: "x", category: "network", label: "Network issue" }],
    };
    expect(sample.schema_version).toBe("3");
    expect(sample.driver_explain?.length).toBe(1);
  });
});
