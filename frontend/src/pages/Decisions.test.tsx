import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  tags: [] as string[],
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
  tags: [] as string[],
  ai_confidence: 0.95,
  created_at: "2026-08-18T09:00:00Z",
};

const SIGNUP_DEGRADED = {
  trace_id: "tr-signup-1",
  short_id: "SIGNUP01",
  event_type: "signup" as const,
  decision: "deny",
  amount: null,
  currency: null,
  rule_result: "REVIEW" as const,
  tags: ["ml:unavailable"],
  ai_confidence: null,
  created_at: "2026-08-18T07:00:00Z",
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

  it("filters signup as a first-class event type", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW, PAYMENT_ALLOW, SIGNUP_DEGRADED],
    });

    render(wrap(<Decisions />));
    await waitFor(() => expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(3));

    fireEvent.change(screen.getByTestId("filter-event-type"), { target: { value: "signup" } });

    expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(1);
    expect(screen.getByTestId("decisions-row-tr-signup-1")).toBeInTheDocument();
  });

  it("shows degraded-path deny as REVIEW, not DENY", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [SIGNUP_DEGRADED],
    });

    render(wrap(<Decisions />));
    await waitFor(() => expect(screen.getByTestId("decisions-row-tr-signup-1")).toBeInTheDocument());
    const row = screen.getByTestId("decisions-row-tr-signup-1");
    expect(row.textContent).toContain("REVIEW");
    expect(row.textContent).not.toContain("DENY");
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

  it("shows pack, rule hits, and integrity present|missing|true on the decision detail", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW],
    });
    vi.mocked(client.decisions.getAudit).mockResolvedValue({
      trace_id: "tr-login-1",
      entity_id: "ent-1",
      tenant_id: "demo",
      event_type: "login",
      decision: "review",
      score: 62,
      tags: ["sdk:rooted"],
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      integrity: {
        is_rooted: "true",
        is_jailbroken: "missing",
        has_biometrics: "missing",
      },
      created_at: "2026-08-24T08:00:00Z",
    });

    render(wrap(<Decisions />, "/decisions/tr-login-1"));

    await waitFor(() => expect(client.decisions.getAudit).toHaveBeenCalled());
    expect(await screen.findByTestId("pack-why-strip")).toBeInTheDocument();
    expect(screen.getByTestId("pack-why-pack")).toHaveTextContent("device_signals");
    expect(screen.getByTestId("pack-why-reason")).toHaveTextContent("sdk_rooted");
    expect(screen.queryByTestId("pack-why-advise")).not.toBeInTheDocument();
    expect(screen.getByTestId("device-integrity-rooted")).toHaveTextContent("true");
    expect(screen.getByTestId("device-integrity-jailbroken")).toHaveTextContent("missing");
    expect(screen.getByTestId("device-integrity-biometrics")).toHaveTextContent("missing");
  });

  it("falls back to minimal audit when analyst detail is 403 and mounts PackWhyStrip from the real payload", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW],
    });
    vi.mocked(client.decisions.getAudit).mockImplementation(async (_tid, _tenant, opts) => {
      if (opts?.detail_level === "analyst") {
        throw new client.ApiRequestError("403 analyst role required for full audit detail", { status: 403 });
      }
      return {
        trace_id: "tr-login-1",
        entity_id: "ent-1",
        tenant_id: "demo",
        event_type: "login",
        decision: "review",
        score: 62,
        tags: [],
        rule_hits: ["sdk_rooted"],
        rule_pack_file: "device_signals.json",
        created_at: "2026-08-24T08:00:00Z",
      };
    });

    render(wrap(<Decisions />, "/decisions/tr-login-1"));

    expect(await screen.findByTestId("pack-why-strip")).toBeInTheDocument();
    expect(screen.getByTestId("pack-why-pack")).toHaveTextContent("device_signals");
    expect(screen.getByTestId("pack-why-reason")).toHaveTextContent("sdk_rooted");
    expect(screen.queryByText("Audit detail unavailable")).not.toBeInTheDocument();
    expect(client.decisions.getAudit).toHaveBeenCalledWith("tr-login-1", "demo", { detail_level: "analyst" });
    expect(client.decisions.getAudit).toHaveBeenCalledWith("tr-login-1", "demo", { detail_level: "minimal" });
  });

  it("shows the fail-closed banner only when analyst and minimal audit both fail", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW],
    });
    vi.mocked(client.decisions.getAudit).mockRejectedValue(
      new client.ApiRequestError("403 analyst role required for full audit detail", { status: 403 }),
    );

    render(wrap(<Decisions />, "/decisions/tr-login-1"));

    expect(await screen.findByText("Audit detail unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("pack-why-strip")).not.toBeInTheDocument();
    expect(screen.queryByText("sdk_rooted")).not.toBeInTheDocument();
    expect(client.decisions.getAudit).toHaveBeenCalledWith("tr-login-1", "demo", { detail_level: "analyst" });
    expect(client.decisions.getAudit).toHaveBeenCalledWith("tr-login-1", "demo", { detail_level: "minimal" });
  });

  it("surfaces pack, rule, and missing integrity on an evaluate-born REVIEW row (not FLAG-renamed)", async () => {
    const flagRow = {
      ...LOGIN_REVIEW,
      trace_id: "tr-review-1",
      short_id: "REV00001",
      decision: "review",
      rule_result: "REVIEW" as const,
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      integrity: {
        is_rooted: "true",
        is_jailbroken: "missing",
        has_biometrics: "missing",
      },
    };
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [flagRow],
    });

    render(wrap(<Decisions />));

    const row = await screen.findByTestId("decisions-row-tr-review-1");
    expect(row.textContent).toContain("device_signals");
    expect(row.textContent).toContain("sdk_rooted");
    expect(row.textContent).toContain("true");
    expect(row.textContent).toContain("missing");
    expect(row.textContent).not.toContain("Advise");
    expect(row.textContent).toContain("REVIEW");
    expect(row.textContent).not.toMatch(/(^|[^A-Z])FLAG([^A-Z]|$)/);
  });

  it("shows decision and pack name without a memorized UUID", async () => {
    const packUuid = "550e8400-e29b-41d4-a716-446655440000";
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [
        {
          ...LOGIN_REVIEW,
          trace_id: packUuid,
          short_id: "LOGIN001",
          decision: "review",
          rule_pack_file: `${packUuid}.json`,
          pack_name: "Device signals",
        },
      ],
    });

    render(wrap(<Decisions />));

    const row = await screen.findByTestId(`decisions-row-${packUuid}`);
    expect(row.textContent).toContain("review");
    const pack = screen.getByTestId(`decisions-pack-${packUuid}`);
    expect(pack).toHaveTextContent("Device signals");
    expect(pack).not.toHaveTextContent(packUuid);
  });

  it("opening a row reaches the receipt-why path", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [
        {
          ...LOGIN_REVIEW,
          rule_pack_file: "device_signals.json",
          rule_hits: ["sdk_rooted"],
        },
      ],
    });
    vi.mocked(client.decisions.getAudit).mockResolvedValue({
      trace_id: "tr-login-1",
      entity_id: "ent-1",
      tenant_id: "demo",
      event_type: "login",
      decision: "review",
      score: 62,
      tags: [],
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      created_at: "2026-08-24T08:00:00Z",
    });

    render(wrap(<Decisions />));
    fireEvent.click(await screen.findByTestId("decisions-row-tr-login-1"));

    expect(await screen.findByTestId("pack-why-strip")).toBeInTheDocument();
    expect(screen.getByTestId("pack-why-pack")).toHaveTextContent("device_signals");
    expect(screen.getByTestId("pack-why-reason")).toHaveTextContent("sdk_rooted");
  });

  it("hints only real next legal actions on a decisions row", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW, PAYMENT_ALLOW],
    });

    render(wrap(<Decisions />));
    await waitFor(() => expect(screen.queryAllByTestId(/decisions-row-/)).toHaveLength(2));

    const review = within(screen.getByTestId("decisions-row-tr-login-1")).getByTestId("next-legal-action");
    expect(review).toHaveTextContent("Open receipt");
    expect(review).toHaveTextContent("Create Observe draft");
    expect(review.textContent?.toLowerCase() ?? "").not.toMatch(/case crm|\bsar\b|open case/);

    const allow = within(screen.getByTestId("decisions-row-tr-pay-1")).getByTestId("next-legal-action");
    expect(allow).toHaveTextContent("Open receipt");
    expect(allow).not.toHaveTextContent("Create Observe draft");
    expect(allow.textContent?.toLowerCase() ?? "").not.toMatch(/case crm|\bsar\b|open case/);
  });

  it("empty decisions uses honest English, not API jargon", async () => {
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [],
    });

    render(wrap(<Decisions />));
    const empty = await screen.findByTestId("decisions-empty");
    const copy = empty.textContent?.toLowerCase() ?? "";
    expect(copy).toMatch(/no recent decisions|no decisions yet/);
    expect(copy).not.toMatch(/audit\/recent|fixture|placeholder|demo fill/);
    expect(empty.textContent ?? "").toMatch(/does not invent|not an outage/i);
  });
});
