import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
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

const sampleCase = {
  id: "c-empty-1",
  title: "Wire fraud review",
  status: "open",
  priority: "high",
  entity_id: "ent-1",
  tenant_id: "demo",
  trace_id: "tr-1",
  assigned_team: "risk",
  labels: [],
  queue_score: 80,
  recommended_action: "manual_review",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

describe("Cases empty states", () => {
  beforeEach(() => {
    vi.mocked(client.cases.list).mockReset();
  });

  it("shows tenant empty copy and New Case when the queue has no rows and no filters", async () => {
    vi.mocked(client.cases.list).mockResolvedValue({ items: [] });
    render(wrap(<Cases />));
    const empty = await screen.findByTestId("cases-empty");
    expect(empty).toHaveTextContent("No cases in tenant");
    expect(empty).toHaveTextContent("demo");
    expect(screen.getAllByRole("button", { name: /new case/i }).length).toBeGreaterThan(0);
    expect(screen.queryByText("No cases found")).not.toBeInTheDocument();
  });

  it("shows No cases match and Clear filters when filters hide every row", async () => {
    vi.mocked(client.cases.list).mockResolvedValue({ items: [sampleCase] });
    render(wrap(<Cases />));
    await screen.findByText("Wire fraud review");
    fireEvent.change(screen.getByPlaceholderText("Search cases..."), { target: { value: "zzzz-no-match" } });
    const empty = await screen.findByTestId("cases-empty");
    expect(empty).toHaveTextContent("No cases match");
    fireEvent.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(await screen.findByText("Wire fraud review")).toBeInTheDocument();
  });

  it("keeps the error banner on API failure and does not use the blank 11-col row as the only empty state", async () => {
    vi.mocked(client.cases.list).mockRejectedValue(new Error("case-api down"));
    render(wrap(<Cases />));
    await waitFor(() => expect(client.cases.list).toHaveBeenCalled());
    expect(await screen.findByText(/Case queue/i)).toBeInTheDocument();
    expect(screen.queryByText("No cases found")).not.toBeInTheDocument();
    expect(screen.queryByTestId("cases-empty")).not.toBeInTheDocument();
  });

  it("labels row checkboxes with the case title", async () => {
    vi.mocked(client.cases.list).mockResolvedValue({ items: [sampleCase] });
    render(wrap(<Cases />));
    expect(await screen.findByRole("checkbox", { name: "Select case Wire fraud review" })).toBeInTheDocument();
  });

  it("does not advertise Shadow LLM hero key S on the lean surface", async () => {
    vi.mocked(client.cases.list).mockResolvedValue({ items: [sampleCase] });
    render(wrap(<Cases />));
    await screen.findByText("Wire fraud review");
    const hero = screen.getByLabelText("Keyboard shortcuts");
    expect(hero).not.toHaveTextContent("Shadow LLM");
    expect(hero).toHaveTextContent("Approve");
    expect(hero).toHaveTextContent("Close");
  });
});
