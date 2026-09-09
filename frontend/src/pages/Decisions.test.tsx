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
      getProductAcks: vi.fn(),
      governance: vi.fn(),
      enforcementJournal: vi.fn(),
      getEnforcementDeliveries: vi.fn(),
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
    vi.mocked(client.decisions.getProductAcks).mockReset();
    vi.mocked(client.decisions.governance).mockReset();
    vi.mocked(client.decisions.enforcementJournal).mockReset();
    vi.mocked(client.decisions.getEnforcementDeliveries).mockReset();
    vi.mocked(client.decisions.getProductAcks).mockResolvedValue({
      schema_id: "tarka.product_ack_list/v1",
      items: [],
    });
    vi.mocked(client.decisions.governance).mockResolvedValue({
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
      experiment_registry_lines: 0,
      drift_smoke: { script: "", note: "" },
      integrity_ingress: { enforcement_webhook_configured: false },
    });
    vi.mocked(client.decisions.enforcementJournal).mockResolvedValue({
      schema_id: "tarka.enforcement_delivery_list/v1",
      items: [],
    });
    vi.mocked(client.decisions.getEnforcementDeliveries).mockResolvedValue({
      schema_id: "tarka.enforcement_delivery_query/v1",
      deliveries: [],
    });
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

  it("shows delivery chips next to pack-why from GET acks + journal", async () => {
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
      tags: [],
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      created_at: "2026-08-24T08:00:00Z",
    });
    vi.mocked(client.decisions.governance).mockResolvedValue({
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
      experiment_registry_lines: 0,
      drift_smoke: { script: "", note: "" },
      integrity_ingress: { enforcement_webhook_configured: true },
    });
    vi.mocked(client.decisions.enforcementJournal).mockResolvedValue({
      schema_id: "tarka.enforcement_delivery_list/v1",
      items: [
        {
          trace_id: "tr-login-1",
          tenant_id: "demo",
          status: "acked",
          enforcement_mode: "emit_only",
        },
      ],
    });
    vi.mocked(client.decisions.getProductAcks).mockResolvedValue({
      schema_id: "tarka.product_ack_list/v1",
      items: [
        {
          schema_id: "tarka.product_ack/v1",
          trace_id: "tr-login-1",
          action_id: "a".repeat(64),
          status: "applied",
          ts: "2026-09-09T04:00:00Z",
          actor: "demo",
        },
      ],
    });

    render(wrap(<Decisions />, "/decisions/tr-login-1"));

    expect(await screen.findByTestId("pack-why-strip")).toBeInTheDocument();
    expect(await screen.findByTestId("delivery-status-strip")).toBeInTheDocument();
    expect(screen.getByTestId("delivery-status-chip")).toHaveAttribute("data-status", "acked");
    expect(screen.getByTestId("delivery-status-chip")).toHaveTextContent(/acked/i);
    expect(client.decisions.getProductAcks).toHaveBeenCalledWith("tr-login-1", "demo");
    const glass = screen.getByTestId("delivery-status-strip").textContent?.toLowerCase() ?? "";
    expect(glass).toMatch(/advisory emit/);
    expect(glass).not.toMatch(/blocked payout|we blocked|promote|demote|case crm/);
  });

  it("empty enforcement webhook URL is not configured, not fake acked", async () => {
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
      tags: [],
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      created_at: "2026-08-24T08:00:00Z",
    });
    vi.mocked(client.decisions.governance).mockResolvedValue({
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
      experiment_registry_lines: 0,
      drift_smoke: { script: "", note: "" },
      integrity_ingress: { enforcement_webhook_configured: false },
    });
    vi.mocked(client.decisions.getProductAcks).mockResolvedValue({
      schema_id: "tarka.product_ack_list/v1",
      items: [
        {
          schema_id: "tarka.product_ack/v1",
          trace_id: "tr-login-1",
          action_id: "b".repeat(64),
          status: "applied",
          ts: "2026-09-09T04:00:00Z",
          actor: "demo",
        },
      ],
    });

    render(wrap(<Decisions />, "/decisions/tr-login-1"));

    expect(await screen.findByTestId("delivery-status-chip")).toHaveAttribute(
      "data-status",
      "not_configured",
    );
    expect(screen.getByTestId("delivery-status-chip")).toHaveTextContent(/not configured/i);
    expect(screen.getByTestId("delivery-status-chip")).not.toHaveTextContent(/^acked$/);
    expect(client.decisions.getProductAcks).toHaveBeenCalledWith("tr-login-1", "demo");
  });

  it("shows failed when the enforcement journal is error / non_2xx", async () => {
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
      tags: [],
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      created_at: "2026-08-24T08:00:00Z",
    });
    vi.mocked(client.decisions.governance).mockResolvedValue({
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
      experiment_registry_lines: 0,
      drift_smoke: { script: "", note: "" },
      integrity_ingress: { enforcement_webhook_configured: true },
    });
    vi.mocked(client.decisions.enforcementJournal).mockResolvedValue({
      schema_id: "tarka.enforcement_delivery_list/v1",
      items: [{ trace_id: "tr-login-1", tenant_id: "demo", status: "error" }],
    });

    render(wrap(<Decisions />, "/decisions/tr-login-1"));
    expect(await screen.findByTestId("delivery-status-chip")).toHaveAttribute("data-status", "failed");
  });

  it("shows emitted when the webhook was delivered and no product ACK exists", async () => {
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
      tags: [],
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      created_at: "2026-08-24T08:00:00Z",
    });
    vi.mocked(client.decisions.governance).mockResolvedValue({
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
      experiment_registry_lines: 0,
      drift_smoke: { script: "", note: "" },
      integrity_ingress: { enforcement_webhook_configured: true },
    });
    vi.mocked(client.decisions.enforcementJournal).mockResolvedValue({
      schema_id: "tarka.enforcement_delivery_list/v1",
      items: [{ trace_id: "tr-login-1", tenant_id: "demo", status: "acked" }],
    });

    render(wrap(<Decisions />, "/decisions/tr-login-1"));
    expect(await screen.findByTestId("delivery-status-chip")).toHaveAttribute("data-status", "emitted");
    expect(screen.getByTestId("delivery-status-hint")).toHaveTextContent(/advisory emit/i);
    expect(screen.getByTestId("delivery-status-hint").textContent?.toLowerCase()).not.toMatch(
      /blocked payout/,
    );
  });

  it("shows retrying / dead_lettered / acked / not_configured from D9.3 GET deliveries", async () => {
    const audit = {
      trace_id: "tr-login-1",
      entity_id: "ent-1",
      tenant_id: "demo",
      event_type: "login" as const,
      decision: "review",
      score: 62,
      tags: [] as string[],
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      created_at: "2026-08-24T08:00:00Z",
    };
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [LOGIN_REVIEW],
    });
    vi.mocked(client.decisions.getAudit).mockResolvedValue(audit);
    vi.mocked(client.decisions.governance).mockResolvedValue({
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
      experiment_registry_lines: 0,
      drift_smoke: { script: "", note: "" },
      integrity_ingress: { enforcement_webhook_configured: true },
    });

    const rows = [
      { chip: "retrying", last_status: "retrying" },
      { chip: "dead_lettered", last_status: "dead_lettered" },
      { chip: "acked", last_status: "acked" },
      { chip: "emitted", last_status: "emitted" },
    ] as const;
    for (const { chip, last_status } of rows) {
      vi.mocked(client.decisions.getEnforcementDeliveries).mockResolvedValue({
        schema_id: "tarka.enforcement_delivery_query/v1",
        deliveries: [
          {
            trace_id: "tr-login-1",
            tenant_id: "demo",
            action_id: "c".repeat(64),
            attempt_count: 2,
            last_status,
            last_error: last_status === "dead_lettered" ? "timeout" : null,
            acked_at: last_status === "acked" ? "2026-09-09T04:00:00Z" : null,
          },
        ],
      });
      const { unmount } = render(wrap(<Decisions />, "/decisions/tr-login-1"));
      expect(await screen.findByTestId("pack-why-strip")).toBeInTheDocument();
      expect(await screen.findByTestId("delivery-status-chip")).toHaveAttribute("data-status", chip);
      expect(screen.getByTestId("delivery-status-strip").textContent?.toLowerCase()).not.toMatch(
        /blocked by tarka|we blocked|case crm|auto-demote/,
      );
      expect(client.decisions.getEnforcementDeliveries).toHaveBeenCalledWith("tr-login-1", "demo");
      unmount();
    }
  });

  it("D9.3 not_configured / empty webhook never fakes acked", async () => {
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
      tags: [],
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      created_at: "2026-08-24T08:00:00Z",
    });
    vi.mocked(client.decisions.governance).mockResolvedValue({
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
      experiment_registry_lines: 0,
      drift_smoke: { script: "", note: "" },
      integrity_ingress: { enforcement_webhook_configured: false },
    });
    vi.mocked(client.decisions.getEnforcementDeliveries).mockResolvedValue({
      schema_id: "tarka.enforcement_delivery_query/v1",
      deliveries: [
        {
          trace_id: "tr-login-1",
          tenant_id: "demo",
          action_id: "d".repeat(64),
          attempt_count: 1,
          last_status: "not_configured",
          last_error: null,
          acked_at: null,
        },
      ],
    });
    vi.mocked(client.decisions.getProductAcks).mockResolvedValue({
      schema_id: "tarka.product_ack_list/v1",
      items: [
        {
          schema_id: "tarka.product_ack/v1",
          trace_id: "tr-login-1",
          action_id: "d".repeat(64),
          status: "applied",
          ts: "2026-09-09T04:00:00Z",
          actor: "demo",
        },
      ],
    });

    render(wrap(<Decisions />, "/decisions/tr-login-1"));
    expect(await screen.findByTestId("delivery-status-chip")).toHaveAttribute(
      "data-status",
      "not_configured",
    );
    expect(screen.getByTestId("delivery-status-chip")).toHaveTextContent(/not configured/i);
    expect(screen.getByTestId("delivery-status-chip")).not.toHaveTextContent(/^acked$/);
    expect(screen.getByTestId("delivery-status-strip").textContent?.toLowerCase()).not.toMatch(
      /blocked by tarka/,
    );
  });

  it("maps residual unclassified D9.3 error to failed, not dead_lettered", async () => {
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
      tags: [],
      rule_hits: ["sdk_rooted"],
      rule_pack_file: "device_signals.json",
      created_at: "2026-08-24T08:00:00Z",
    });
    vi.mocked(client.decisions.governance).mockResolvedValue({
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
      experiment_registry_lines: 0,
      drift_smoke: { script: "", note: "" },
      integrity_ingress: { enforcement_webhook_configured: true },
    });
    vi.mocked(client.decisions.getEnforcementDeliveries).mockResolvedValue({
      schema_id: "tarka.enforcement_delivery_query/v1",
      deliveries: [
        {
          trace_id: "tr-login-1",
          tenant_id: "demo",
          action_id: "e".repeat(64),
          attempt_count: 1,
          last_status: "error",
          last_error: "boom",
          acked_at: null,
        },
      ],
    });

    render(wrap(<Decisions />, "/decisions/tr-login-1"));
    expect(await screen.findByTestId("delivery-status-chip")).toHaveAttribute("data-status", "failed");
    expect(screen.queryByText(/^dead lettered$/i)).not.toBeInTheDocument();
  });
});
