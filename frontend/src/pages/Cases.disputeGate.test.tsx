import type { ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { AnalystWorkspaceProvider } from "@/context/AnalystWorkspaceContext";
import { TenantEnvironmentProvider } from "@/context/TenantEnvironmentContext";
import { ToastProvider } from "@/context/ToastContext";
import Cases from "@/pages/Cases";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    cases: {
      ...actual.cases,
      list: vi.fn(),
      playbooks: vi.fn().mockResolvedValue({ playbooks: {} }),
      listViews: vi.fn().mockResolvedValue({ items: [] }),
      opsKpis: vi.fn().mockRejectedValue(new Error("skip")),
      cohortCompare: vi.fn().mockRejectedValue(new Error("skip")),
      deskActivity: vi.fn().mockRejectedValue(new Error("skip")),
    },
  };
});

function wrap(ui: ReactElement) {
  return (
    <MemoryRouter initialEntries={["/cases"]}>
      <TenantEnvironmentProvider>
        <AnalystWorkspaceProvider>
          <ToastProvider>
            <Routes>
              <Route path="/cases" element={ui} />
            </Routes>
          </ToastProvider>
        </AnalystWorkspaceProvider>
      </TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

describe("Cases dashboard (Prompt 122 gate)", () => {
  beforeEach(() => {
    vi.mocked(client.cases.list).mockResolvedValue({
      items: [
        {
          id: "cb-gate-1",
          title: "Chargeback — merchant dispute",
          status: "open",
          priority: "high",
          entity_id: "ent-chargeback-gate",
          tenant_id: "demo",
          trace_id: "tr-cb-gate",
          assigned_team: "disputes",
          labels: ["Dispute"],
          queue_score: 80,
          recommended_action: "manual_review",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    });
  });

  it("shows a Dispute label badge for chargeback-tagged cases", async () => {
    render(wrap(<Cases />));
    await waitFor(() => expect(client.cases.list).toHaveBeenCalled());
    expect(await screen.findByTestId("case-label-dispute")).toHaveTextContent("Dispute");
  });
});
