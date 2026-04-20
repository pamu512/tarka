import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { EvaluationPostureResponse } from "../api/client";
import { AnalystReadinessBar } from "./AnalystReadinessBar";

vi.mock("../api/client", () => ({
  decisions: {
    evaluationPosture: vi.fn(),
    slo: vi.fn(),
  },
}));

import { decisions } from "../api/client";

const mockEvaluationPosture = vi.mocked(decisions.evaluationPosture);
const mockSlo = vi.mocked(decisions.slo);

function degradedCompliancePosture(): EvaluationPostureResponse {
  return {
    service: "decision-api",
    deployment_tier: "pro",
    tenant_reliability_profile: "balanced",
    evaluation_mode: "compliance",
    compliance_posture: "strict",
    compliance_degraded: true,
    compliance_degraded_reasons: ["typologies_empty"],
    typology_count: 0,
    predicate_registry_version: 1,
    predicate_registry_pin_match: true,
    dependencies: [
      { id: "redis", ok: true },
      { id: "graph_service_configured", ok: true },
    ],
    last_rules_reload_at: "2026-04-20T15:30:00.000Z",
    runbook_url: "https://example.com/runbook",
  };
}

const healthySlo = {
  service: "decision-api",
  current: { redis_connected: true, nats_connected: true },
};

describe("AnalystReadinessBar", () => {
  beforeEach(() => {
    mockEvaluationPosture.mockReset();
    mockSlo.mockReset();
  });

  it("shows degraded compliance alert and config reload on the trust/ops strip (OSS #36)", async () => {
    mockEvaluationPosture.mockResolvedValue(degradedCompliancePosture());
    mockSlo.mockResolvedValue(healthySlo);

    render(
      <MemoryRouter>
        <AnalystReadinessBar />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByRole("region", { name: /trust and operations readiness/i })).toBeInTheDocument();
    });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/Compliance prerequisites degraded/i);
    expect(alert).toHaveTextContent(/typologies_empty/i);

    expect(screen.getByText(/Config reload:/i)).toBeInTheDocument();
    expect(screen.getByTitle(/last_rules_reload_at/i)).toBeInTheDocument();
  });

  it("does not show a compliance alert when posture is healthy in detection mode", async () => {
    const healthy: EvaluationPostureResponse = {
      service: "decision-api",
      deployment_tier: "pro",
      tenant_reliability_profile: "balanced",
      evaluation_mode: "detection",
      compliance_posture: "nominal",
      compliance_degraded: false,
      compliance_degraded_reasons: [],
      typology_count: 3,
      predicate_registry_version: 1,
      predicate_registry_pin_match: true,
      dependencies: [{ id: "redis", ok: true }],
      last_rules_reload_at: "2026-04-20T15:30:00.000Z",
      runbook_url: "https://example.com/runbook",
    };
    mockEvaluationPosture.mockResolvedValue(healthy);
    mockSlo.mockResolvedValue(healthySlo);

    render(
      <MemoryRouter>
        <AnalystReadinessBar />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Detection evaluation/i)).toBeInTheDocument();
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
