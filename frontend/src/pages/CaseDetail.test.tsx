import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { AnalystWorkspaceProvider } from "@/context/AnalystWorkspaceContext";
import { PageMetaProvider } from "@/context/PageMetaContext";
import { TenantEnvironmentProvider } from "@/context/TenantEnvironmentContext";
import { ToastProvider } from "@/context/ToastContext";
import CaseDetail from "@/pages/CaseDetail";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    cases: {
      ...actual.cases,
      get: vi.fn(),
      update: vi.fn(),
      addComment: vi.fn(),
      addLabels: vi.fn(),
      evidenceBundle: vi.fn(),
    },
    decisions: {
      ...actual.decisions,
      getAudit: vi.fn().mockRejectedValue(new Error("skip")),
      reliabilityBins: vi.fn().mockRejectedValue(new Error("skip")),
      joinDispositionLabels: vi.fn(),
      dispatchChallenge: vi.fn(),
    },
    graph: {
      ...actual.graph,
      entityRisk: vi.fn().mockRejectedValue(new Error("skip")),
      subgraph: vi.fn().mockRejectedValue(new Error("skip")),
      riskPropagation: vi.fn().mockResolvedValue({ entities: [] }),
      getEntity: vi.fn().mockResolvedValue(null),
      entityLinks: vi.fn().mockResolvedValue(null),
      entityHistory: vi.fn().mockResolvedValue(null),
      entityDeepContext: vi.fn().mockResolvedValue(null),
    },
    disputes: {
      ...actual.disputes,
      create: vi.fn(),
    },
  };
});

function wrap(ui: ReactElement, path = "/cases/c-1?tenant_id=demo") {
  return (
    <MemoryRouter initialEntries={[path]}>
      <TenantEnvironmentProvider>
        <AnalystWorkspaceProvider>
          <PageMetaProvider>
            <ToastProvider>
              <Routes>
                <Route path="/cases/:caseId" element={ui} />
              </Routes>
            </ToastProvider>
          </PageMetaProvider>
        </AnalystWorkspaceProvider>
      </TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

function makeCase(overrides: Record<string, unknown> = {}) {
  return {
    id: "c-1",
    title: "ATO review",
    status: "investigating",
    priority: "high",
    entity_id: "ent-1",
    tenant_id: "demo",
    trace_id: "tr-1",
    assigned_team: "risk",
    labels: [],
    queue_score: 70,
    recommended_action: "manual_review",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    comments: [],
    ...overrides,
  };
}

describe("CaseDetail disposition bar", () => {
  beforeEach(() => {
    vi.mocked(client.cases.get).mockReset();
    vi.mocked(client.cases.update).mockReset();
    vi.mocked(client.decisions.joinDispositionLabels).mockReset();
    vi.mocked(client.cases.update).mockImplementation(async (_id, _tenant, data) =>
      makeCase({ ...data, id: "c-1" }),
    );
    vi.mocked(client.decisions.joinDispositionLabels).mockResolvedValue({ schema_id: "ok" });
  });

  it("renders a sticky verdict bar with reason codes and Resolve / Close / keep investigating", async () => {
    vi.mocked(client.cases.get).mockResolvedValue(makeCase());
    render(wrap(<CaseDetail />));
    const bar = await screen.findByTestId("disposition-bar");
    expect(bar).toHaveTextContent("Verdict");
    expect(screen.getByTestId("disposition-reason")).toBeInTheDocument();
    expect(screen.getByTestId("disposition-resolve")).toHaveTextContent("Resolve");
    expect(screen.getByTestId("disposition-close")).toHaveTextContent("Close");
    expect(screen.getByTestId("disposition-investigate")).toHaveTextContent("Keep investigating");
    expect(screen.getByRole("option", { name: "Confirmed fraud" })).toBeInTheDocument();
    expect(screen.queryByText("Copilot rail: open")).not.toBeInTheDocument();
    expect(screen.queryByText("Knowledge graph: open")).not.toBeInTheDocument();
  });

  it("wires Resolve to cases.update with disposition_reason_code and joins y_label", async () => {
    vi.mocked(client.cases.get).mockResolvedValue(makeCase());
    render(wrap(<CaseDetail />));
    await screen.findByTestId("disposition-bar");
    fireEvent.change(screen.getByTestId("disposition-reason"), { target: { value: "CONFIRMED_FRAUD" } });
    fireEvent.click(screen.getByTestId("disposition-resolve"));
    await waitFor(() => expect(client.cases.update).toHaveBeenCalled());
    expect(client.cases.update).toHaveBeenCalledWith(
      "c-1",
      "demo",
      expect.objectContaining({ status: "resolved", disposition_reason_code: "CONFIRMED_FRAUD" }),
    );
    await waitFor(() => expect(client.decisions.joinDispositionLabels).toHaveBeenCalled());
    expect(client.decisions.joinDispositionLabels).toHaveBeenCalledWith(
      "demo",
      expect.objectContaining({ labels_by_trace: { "tr-1": "FRAUD" } }),
    );
  });

  it("still updates the case when trace_id is missing and skips calibration join", async () => {
    vi.mocked(client.cases.get).mockResolvedValue(makeCase({ trace_id: "" }));
    render(wrap(<CaseDetail />));
    await screen.findByTestId("disposition-bar");
    fireEvent.change(screen.getByTestId("disposition-reason"), { target: { value: "FALSE_POSITIVE" } });
    fireEvent.click(screen.getByTestId("disposition-close"));
    await waitFor(() => expect(client.cases.update).toHaveBeenCalled());
    expect(client.cases.update).toHaveBeenCalledWith(
      "c-1",
      "demo",
      expect.objectContaining({ status: "closed", disposition_reason_code: "FALSE_POSITIVE" }),
    );
    expect(client.decisions.joinDispositionLabels).not.toHaveBeenCalled();
  });
});


describe("CaseDetail pack why strip", () => {
  beforeEach(() => {
    vi.mocked(client.cases.get).mockReset();
    vi.mocked(client.decisions.getAudit).mockReset();
    vi.mocked(client.decisions.getAudit).mockRejectedValue(new Error("skip"));
    vi.mocked(client.decisions.reliabilityBins).mockRejectedValue(new Error("skip"));
    vi.mocked(client.graph.entityRisk).mockRejectedValue(new Error("skip"));
  });

  it("always paints the pack-why strip and says missing when the pack reason is absent", async () => {
    vi.mocked(client.cases.get).mockResolvedValue(makeCase());
    render(wrap(<CaseDetail />));
    const strip = await screen.findByTestId("pack-why-strip");
    expect(strip).toBeInTheDocument();
    expect(screen.getByTestId("pack-why-reason")).toHaveTextContent("missing");
    expect(screen.queryByTestId("pack-why-advise")).not.toBeInTheDocument();
  });

  it("shows the pack that fired and one why from the evaluate/audit snapshot", async () => {
    vi.mocked(client.cases.get).mockResolvedValue(makeCase());
    vi.mocked(client.decisions.getAudit).mockResolvedValue({
      trace_id: "tr-1",
      entity_id: "ent-1",
      tenant_id: "demo",
      event_type: "payment",
      decision: "review",
      score: 74,
      tags: [],
      rule_hits: ["velocity_guard"],
      rule_pack_file: "fintech.json",
      recommended_action: "manual_review",
      inference_context: {
        schema_version: "3",
        calibration_profile: "default",
        expected_calibration_version: 1,
        integrity_confidence: 0,
        tamper_risk: 0,
        network_trust: 0,
        replay_risk: 0,
        geo_consistency_risk: 0,
        top_signals: [],
        confidence_tier: "medium",
        driver_reasons: ["rule:velocity_guard"],
        driver_explain: [{ reason: "rule:velocity_guard", category: "rules", label: "Velocity burst on this card" }],
        colocation_risk: 0,
        copresence_risk: 0,
        impossible_travel_risk: 0,
        velocity_events_5m: 0,
        velocity_events_1h: 0,
        velocity_events_24h: 0,
        calibration_profile_version: 1,
        location_confidence: 0,
        confidence_sources: { calibration: "heuristic", counter: "heuristic", location: "heuristic" },
        graph_risk_score: 0,
        graph_risk_reasons: [],
        external_signal_score: 0,
        external_signal_providers: [],
      },
      created_at: new Date().toISOString(),
    });
    render(wrap(<CaseDetail />));
    await screen.findByTestId("pack-why-strip");
    await waitFor(() => {
      expect(screen.getByTestId("pack-why-pack")).toHaveTextContent("fintech");
      expect(screen.getByTestId("pack-why-reason")).toHaveTextContent("Velocity burst on this card");
    });
    expect(screen.queryByTestId("pack-why-advise")).not.toBeInTheDocument();
  });
});

describe("CaseDetail device integrity strip", () => {
  beforeEach(() => {
    vi.mocked(client.cases.get).mockReset();
    vi.mocked(client.decisions.getAudit).mockReset();
    vi.mocked(client.decisions.getAudit).mockRejectedValue(new Error("skip"));
    vi.mocked(client.decisions.reliabilityBins).mockRejectedValue(new Error("skip"));
    vi.mocked(client.graph.entityRisk).mockRejectedValue(new Error("skip"));
  });

  it("always paints the device-integrity strip and says missing when native fields are absent", async () => {
    vi.mocked(client.cases.get).mockResolvedValue(makeCase());
    render(wrap(<CaseDetail />));
    const strip = await screen.findByTestId("device-integrity-strip");
    expect(strip).toBeInTheDocument();
    const hunt = await screen.findByTestId("hunt-this-object");
    expect(hunt).toHaveAttribute("href", "/graph?entity_id=ent-1&tenant_id=demo");
    expect(hunt).toHaveTextContent("Hunt this object");
    expect(screen.getByTestId("device-integrity-rooted")).toHaveTextContent("missing");
    expect(screen.getByTestId("device-integrity-jailbroken")).toHaveTextContent("missing");
    expect(screen.getByTestId("device-integrity-biometrics")).toHaveTextContent("missing");
  });

  it("shows rooted / jailbroken / biometrics from device_context and tags on the open case", async () => {
    vi.mocked(client.cases.get).mockResolvedValue(makeCase());
    vi.mocked(client.decisions.getAudit).mockResolvedValue({
      trace_id: "tr-1",
      entity_id: "ent-1",
      tenant_id: "demo",
      event_type: "payment",
      decision: "review",
      score: 74,
      tags: ["sdk:rooted"],
      rule_hits: [],
      recommended_action: "manual_review",
      evaluate_payload: {
        device_context: {
          platform: "ios",
          signals: { is_jailbroken: true, has_biometrics: false },
        },
      },
      inference_context: {
        schema_version: "3",
        calibration_profile: "default",
        expected_calibration_version: 1,
        integrity_confidence: 0,
        tamper_risk: 0,
        network_trust: 0,
        replay_risk: 0,
        geo_consistency_risk: 0,
        top_signals: [],
        confidence_tier: "medium",
        driver_reasons: [],
        driver_explain: [],
        colocation_risk: 0,
        copresence_risk: 0,
        impossible_travel_risk: 0,
        velocity_events_5m: 0,
        velocity_events_1h: 0,
        velocity_events_24h: 0,
        calibration_profile_version: 1,
        location_confidence: 0,
        confidence_sources: { calibration: "heuristic", counter: "heuristic", location: "heuristic" },
        graph_risk_score: 0,
        graph_risk_reasons: [],
        external_signal_score: 0,
        external_signal_providers: [],
      },
      created_at: new Date().toISOString(),
    });
    render(wrap(<CaseDetail />));
    await screen.findByTestId("device-integrity-strip");
    await waitFor(() => {
      expect(screen.getByTestId("device-integrity-rooted")).toHaveTextContent("yes");
      expect(screen.getByTestId("device-integrity-jailbroken")).toHaveTextContent("yes");
      expect(screen.getByTestId("device-integrity-biometrics")).toHaveTextContent("no");
    });
  });
});
