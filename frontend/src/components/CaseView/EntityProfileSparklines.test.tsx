import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { InferenceContext } from "../../api/inferenceContext";
import { EntityProfileSparklines } from "./EntityProfileSparklines";

function minimalInference(overrides: Partial<InferenceContext> = {}): InferenceContext {
  return {
    schema_version: "1",
    calibration_profile: "default",
    expected_calibration_version: 1,
    calibration_profile_version: 1,
    location_confidence: 0.5,
    confidence_sources: { calibration: "ok", counter: "ok", location: "ok" },
    graph_risk_score: 0.2,
    graph_risk_reasons: [],
    external_signal_score: 0,
    external_signal_providers: [],
    policy_experiment_id: null,
    confidence_tier_label: "medium",
    driver_explain: [],
    integrity_confidence: 0.9,
    tamper_risk: 0.1,
    network_trust: 0.8,
    replay_risk: 0.05,
    geo_consistency_risk: 0.1,
    top_signals: [],
    confidence_tier: "medium",
    driver_reasons: [],
    colocation_risk: 0,
    copresence_risk: 0,
    impossible_travel_risk: 0,
    velocity_events_5m: 1,
    velocity_events_1h: 4,
    velocity_events_24h: 12,
    velocity_events_by_hour_utc: Array.from({ length: 24 }, (_, h) => (h === 10 ? 8 : 0)),
    ml_top_factors: [],
    ml_summary: null,
    ml_model: null,
    ...overrides,
  };
}

describe("EntityProfileSparklines", () => {
  it("renders spend and event sparklines when velocity data and cohort amount exist", () => {
    render(
      <EntityProfileSparklines
        entityId="fraud_frank"
        inference={minimalInference()}
        cohortSpend={{ amount: 1200, currency: "USD" }}
        lastUpdatedIso={new Date().toISOString()}
      />,
    );
    expect(screen.getByTestId("entity-profile-sparklines")).toBeInTheDocument();
    expect(screen.getByText(/User profile — velocity/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Estimated hourly spend trend/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Transaction event counts per UTC hour/i)).toBeInTheDocument();
  });

  it("shows empty state without inference", () => {
    render(<EntityProfileSparklines entityId="user_x" inference={null} />);
    expect(screen.getByText(/No inference \/ velocity payload yet/i)).toBeInTheDocument();
  });
});
