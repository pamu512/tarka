import type { ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { TenantEnvironmentProvider } from "@/context/TenantEnvironmentContext";
import Decisions from "@/pages/Decisions";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    decisions: {
      ...actual.decisions,
      recentAudit: vi.fn(),
      getAudit: vi.fn(),
    },
  };
});

function wrap(ui: ReactElement, path = "/decisions") {
  return (
    <MemoryRouter initialEntries={[path]}>
      <TenantEnvironmentProvider>
        <Routes>
          <Route path="/decisions" element={ui} />
          <Route path="/decisions/:traceId" element={ui} />
        </Routes>
      </TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

describe("Decisions queue", () => {
  beforeEach(() => {
    vi.mocked(client.decisions.recentAudit).mockReset();
    vi.mocked(client.decisions.getAudit).mockReset();
  });

  it("shows a fail-closed empty state when audit/recent returns no rows", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [],
    });

    render(wrap(<Decisions />));

    await waitFor(() => expect(client.decisions.recentAudit).toHaveBeenCalled());
    expect(await screen.findByTestId("decisions-empty")).toHaveTextContent("No recent decisions");
    expect(screen.queryByTestId(/decisions-row-/)).not.toBeInTheDocument();
    expect(screen.queryByText("promo-abuse-live")).not.toBeInTheDocument();
  });

  it("renders live rows from recentAudit and does not invent extras", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [
        {
          trace_id: "tr-live-1",
          short_id: "a000001",
          amount: 42.5,
          currency: "USD",
          rule_result: "REVIEW",
          ai_confidence: 0.81,
          created_at: "2026-08-18T08:00:00Z",
        },
      ],
    });

    render(wrap(<Decisions />));

    await waitFor(() => expect(screen.getByTestId("decisions-row-tr-live-1")).toBeInTheDocument());
    expect(screen.getByText("a000001")).toBeInTheDocument();
    expect(screen.getByText("REVIEW")).toBeInTheDocument();
    expect(screen.getByText("42.5 USD")).toBeInTheDocument();
    expect(screen.getByText("tr-live-1")).toBeInTheDocument();
    expect(screen.queryByTestId("decisions-empty")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(1);
  });
});
