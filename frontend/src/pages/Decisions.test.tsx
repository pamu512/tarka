import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const LOGIN_REVIEW = {
  trace_id: "tr-login-1",
  short_id: "LOGIN001",
  event_type: "login" as const,
  decision: "review",
  amount: null,
  currency: null,
  rule_result: "REVIEW" as const,
  ai_confidence: 0.6,
  created_at: "2026-08-18T08:00:00Z",
};

const PAYMENT_ALLOW = {
  trace_id: "tr-pay-1",
  short_id: "PAY00001",
  event_type: "payment" as const,
  decision: "allow",
  amount: 42,
  currency: "USD",
  rule_result: "ALLOW" as const,
  ai_confidence: 0.95,
  created_at: "2026-08-18T09:00:00Z",
};

describe("Decisions stream", () => {
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

  it("renders live rows with event_type and decision columns", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW, PAYMENT_ALLOW],
    });

    render(wrap(<Decisions />));

    await waitFor(() => expect(screen.getByTestId("decisions-row-tr-login-1")).toBeInTheDocument());
    const loginRow = screen.getByTestId("decisions-row-tr-login-1");
    expect(loginRow.textContent).toContain("login");
    expect(loginRow.textContent).toContain("review");
    const payRow = screen.getByTestId("decisions-row-tr-pay-1");
    expect(payRow.textContent).toContain("payment");
    expect(payRow.textContent).toContain("allow");
    expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(2);
  });

  it("filters by event type", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW, PAYMENT_ALLOW],
    });

    render(wrap(<Decisions />));
    await waitFor(() => expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(2));

    fireEvent.change(screen.getByTestId("filter-event-type"), { target: { value: "login" } });

    expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(1);
    expect(screen.getByTestId("decisions-row-tr-login-1")).toBeInTheDocument();
    expect(screen.queryByTestId("decisions-row-tr-pay-1")).not.toBeInTheDocument();
  });

  it("filters by rule result", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW, PAYMENT_ALLOW],
    });

    render(wrap(<Decisions />));
    await waitFor(() => expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(2));

    fireEvent.change(screen.getByTestId("filter-rule-result"), { target: { value: "ALLOW" } });

    expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(1);
    expect(screen.getByTestId("decisions-row-tr-pay-1")).toBeInTheDocument();
    expect(screen.queryByTestId("decisions-row-tr-login-1")).not.toBeInTheDocument();
  });

  it("shows filter-empty message when filters exclude all rows", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW, PAYMENT_ALLOW],
    });

    render(wrap(<Decisions />));
    await waitFor(() => expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(2));

    fireEvent.change(screen.getByTestId("filter-event-type"), { target: { value: "login" } });
    fireEvent.change(screen.getByTestId("filter-rule-result"), { target: { value: "ALLOW" } });

    expect(screen.getByTestId("decisions-empty")).toHaveTextContent("No decisions match");
  });

  it("does not mention chargebacks or payment inbox in copy", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [],
    });

    render(wrap(<Decisions />));
    await waitFor(() => expect(client.decisions.recentAudit).toHaveBeenCalled());

    const text = document.body.textContent?.toLowerCase() ?? "";
    expect(text).not.toContain("chargeback");
    expect(text).not.toContain("payment queue");
    expect(text).not.toContain("payment inbox");
  });
});
