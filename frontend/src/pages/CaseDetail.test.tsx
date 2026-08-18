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
