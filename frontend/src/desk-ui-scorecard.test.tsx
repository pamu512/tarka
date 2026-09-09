/**
 * UX0.7 T1–T4 click-bar smoke. T5 = late-label API tests. T6 = PlaneOff tests.
 * leftover REVIEW (not FLAG). Primary metric = clicks / steps vs MEP.
 * D9.4 desk delivery glass on the existing G4.4 strip.
 * Delivery reliability ≠ enforcement SKU suite. Not a case CRM.
 */
import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { ObserveEasePanel } from "@/components/ObserveEasePanel";
import { TenantEnvironmentProvider } from "@/context/TenantEnvironmentContext";
import Decisions from "@/pages/Decisions";
import Leftovers from "@/pages/Leftovers";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    cases: {
      ...actual.cases,
      listLeftovers: vi.fn(),
      claimLeftover: vi.fn(),
    },
    rules: {
      ...actual.rules,
      createL2Draft: vi.fn(),
      list: vi.fn(),
      proposeDemote: vi.fn(),
      confirmDemote: vi.fn(),
    },
    decisions: {
      ...actual.decisions,
      queueSeam: vi.fn(),
      recentAudit: vi.fn(),
      getAudit: vi.fn(),
      byomStatus: vi.fn(),
      getProductAcks: vi.fn(),
      governance: vi.fn(),
      enforcementJournal: vi.fn(),
      getEnforcementDeliveries: vi.fn(),
    },
    shadow: {
      ...actual.shadow,
      setPackMode: vi.fn(),
    },
  };
});

function wrapLeftovers(ui: ReactElement) {
  return (
    <MemoryRouter initialEntries={["/leftovers"]}>
      <TenantEnvironmentProvider>
        <Routes>
          <Route path="/leftovers" element={ui} />
          <Route path="/decisions" element={<Decisions />} />
          <Route path="/decisions/:traceId" element={<Decisions />} />
        </Routes>
      </TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

function wrapDecisions(path = "/decisions") {
  return (
    <MemoryRouter initialEntries={[path]}>
      <TenantEnvironmentProvider>
        <Routes>
          <Route path="/decisions" element={<Decisions />} />
          <Route path="/decisions/:traceId" element={<Decisions />} />
        </Routes>
      </TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

function wrap(ui: ReactElement, path = "/decisions/tr-login-1") {
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

const leftoverReview = {
  leftover_id: "c-review",
  entity_id: "buyer-review",
  origin: "evaluate" as const,
  last_outcome: "review",
  last_act: "held" as const,
  claimed_by: null,
  sla_breached: false,
  trace_id: "tr-review",
  brief: "Pack device_signals — hits sdk_bot",
  pack_id: "device_signals",
  rule_hits: ["sdk_bot"],
};

describe("desk UI scorecard T1–T4", () => {
  beforeEach(() => {
    vi.mocked(client.cases.listLeftovers).mockReset();
    vi.mocked(client.cases.claimLeftover).mockReset();
    vi.mocked(client.rules.createL2Draft).mockReset();
    vi.mocked(client.rules.list).mockReset();
    vi.mocked(client.rules.proposeDemote).mockReset();
    vi.mocked(client.rules.confirmDemote).mockReset();
    vi.mocked(client.decisions.queueSeam).mockReset();
    vi.mocked(client.decisions.recentAudit).mockReset();
    vi.mocked(client.decisions.getAudit).mockReset();
    vi.mocked(client.decisions.byomStatus).mockReset();
    vi.mocked(client.shadow.setPackMode).mockReset();

    vi.mocked(client.cases.listLeftovers).mockResolvedValue({ leftovers: [leftoverReview], truncated: false });
    vi.mocked(client.decisions.queueSeam).mockResolvedValue({ connected: false });
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({ tenant_id: "demo", items: [] });
    vi.mocked(client.rules.createL2Draft).mockResolvedValue({
      file: "l2.json",
      pack: { mode: "shadow" },
    });
    vi.mocked(client.decisions.byomStatus).mockResolvedValue({
      connected: false,
      backend: "",
      model: "",
    });
    vi.mocked(client.rules.list).mockResolvedValue({ packs: [] });
  });

  it("T1 MEP 1 click: leftover REVIEW + Open receipt shows receipt-why (not FLAG)", async () => {
    vi.mocked(client.decisions.getAudit).mockResolvedValue({
      trace_id: "tr-review",
      entity_id: "buyer-review",
      tenant_id: "demo",
      event_type: "login",
      decision: "review",
      score: 40,
      tags: [],
      rule_hits: ["sdk_bot"],
      rule_pack_file: "device_signals.json",
      created_at: "2026-08-24T08:00:00Z",
    });

    render(wrapLeftovers(<Leftovers />));
    expect(await screen.findByText("buyer-review")).toBeInTheDocument();
    expect(document.body.textContent).toMatch(/REVIEW/i);
    expect(screen.getByText("review")).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/(^|[^A-Z])FLAG([^A-Z]|$)/);

    const opens = await screen.findAllByRole("link", { name: /open receipt/i });
    fireEvent.click(opens[0]);

    expect(await screen.findByTestId("pack-why-strip")).toBeInTheDocument();
    expect(screen.getByTestId("pack-why-pack")).toHaveTextContent("device_signals");
    expect(screen.getByTestId("pack-why-reason")).toHaveTextContent("sdk_bot");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("T2 MEP type-why + 1 click: Create draft stays off until why; brief is not why", async () => {
    render(wrapLeftovers(<Leftovers />));
    const create = (await screen.findAllByRole("button", { name: /create draft/i }))[0];
    expect(create).toBeDisabled();
    fireEvent.click(create);
    expect(client.rules.createL2Draft).not.toHaveBeenCalled();

    fireEvent.change(screen.getAllByTestId("leftover-override-why")[0], {
      target: { value: "human leftover why" },
    });
    expect(create).toBeEnabled();
    fireEvent.click(create);

    await waitFor(() => {
      expect(client.rules.createL2Draft).toHaveBeenCalledWith(
        expect.objectContaining({
          leftover_id: "c-review",
          override_why: "human leftover why",
        }),
        "demo",
      );
    });
    expect(client.rules.createL2Draft).toHaveBeenCalledWith(
      expect.not.objectContaining({ override_why: leftoverReview.brief }),
      "demo",
    );
    expect(await screen.findByTestId("leftover-saved-why")).toHaveTextContent("human leftover why");
  });

  it("T3 MEP 2 clicks: Promote requires Confirm; Cancel is not a silent Promote", async () => {
    const onPromote = vi.fn();
    render(
      <MemoryRouter>
        <ObserveEasePanel
          tenantId="demo"
          drafts={[{ name: "draft_a", file: "draft_a.json" }]}
          promoteAllowed
          blockers={[]}
          slipRules={[]}
          selectedDraft="draft_a"
          onSelectDraft={() => {}}
          onPromote={onPromote}
          canPromote
        />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /promote draft/i }));
    expect(onPromote).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog", { name: /promote to active/i });
    expect(dialog).toHaveTextContent("draft_a");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onPromote).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /promote draft/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(onPromote).toHaveBeenCalledTimes(1);
    expect(client.shadow.setPackMode).not.toHaveBeenCalled();
  });

  it("T4 MEP 0 extra clicks: pack name on Decisions row, not a memorized UUID", async () => {
    const packUuid = "550e8400-e29b-41d4-a716-446655440000";
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [
        {
          trace_id: packUuid,
          short_id: "LOGIN001",
          event_type: "login",
          decision: "review",
          amount: null,
          currency: null,
          rule_result: "REVIEW",
          tags: [],
          ai_confidence: 0.6,
          created_at: "2026-08-18T08:00:00Z",
          rule_pack_file: `${packUuid}.json`,
          pack_name: "Device signals",
        },
      ],
    });

    render(wrapDecisions());
    const row = await screen.findByTestId(`decisions-row-${packUuid}`);
    expect(row.textContent).toMatch(/REVIEW/i);
    expect(row.textContent ?? "").not.toMatch(/(^|[^A-Z])FLAG([^A-Z]|$)/);
    const pack = screen.getByTestId(`decisions-pack-${packUuid}`);
    expect(pack).toHaveTextContent("Device signals");
    expect(pack).not.toHaveTextContent(packUuid);
  });
});

describe("desk UI scorecard — D9.4 delivery reliability glass", () => {
  beforeEach(() => {
    vi.mocked(client.decisions.recentAudit).mockReset();
    vi.mocked(client.decisions.getAudit).mockReset();
    vi.mocked(client.decisions.getProductAcks).mockReset();
    vi.mocked(client.decisions.governance).mockReset();
    vi.mocked(client.decisions.enforcementJournal).mockReset();
    vi.mocked(client.decisions.getEnforcementDeliveries).mockReset();
    vi.mocked(client.decisions.recentAudit).mockResolvedValue({
      tenant_id: "demo",
      items: [
        {
          trace_id: "tr-login-1",
          short_id: "LOGIN001",
          event_type: "login",
          decision: "review",
          amount: null,
          currency: null,
          rule_result: "REVIEW",
          tags: [],
          ai_confidence: 0.6,
          created_at: "2026-08-18T08:00:00Z",
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
    vi.mocked(client.decisions.getProductAcks).mockResolvedValue({
      schema_id: "tarka.product_ack_list/v1",
      items: [],
    });
    vi.mocked(client.decisions.enforcementJournal).mockResolvedValue({
      schema_id: "tarka.enforcement_delivery_list/v1",
      items: [],
    });
    vi.mocked(client.decisions.governance).mockResolvedValue({
      inference_schema_version: "3",
      rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
      experiment_registry_lines: 0,
      drift_smoke: { script: "", note: "" },
      integrity_ingress: { enforcement_webhook_configured: true },
    });
  });

  it("one strip shows emitted / retrying / dead_lettered / acked / not_configured", async () => {
    const chips = [
      { last_status: "emitted", chip: "emitted" },
      { last_status: "retrying", chip: "retrying" },
      { last_status: "dead_lettered", chip: "dead_lettered" },
      { last_status: "acked", chip: "acked" },
      { last_status: "not_configured", chip: "not_configured", webhook: false },
    ] as const;
    for (const row of chips) {
      vi.mocked(client.decisions.governance).mockResolvedValue({
        inference_schema_version: "3",
        rule_packs: { active_pack_count: 0, shadow_pack_count: 0, packs: [] },
        experiment_registry_lines: 0,
        drift_smoke: { script: "", note: "" },
        integrity_ingress: { enforcement_webhook_configured: row.webhook !== false },
      });
      vi.mocked(client.decisions.getEnforcementDeliveries).mockResolvedValue({
        schema_id: "tarka.enforcement_delivery_query/v1",
        deliveries: [
          {
            trace_id: "tr-login-1",
            tenant_id: "demo",
            action_id: "f".repeat(64),
            attempt_count: 1,
            last_status: row.last_status,
            last_error: null,
            acked_at: null,
          },
        ],
      });
      const { unmount } = render(wrap(<Decisions />));
      expect(await screen.findByTestId("delivery-status-strip")).toBeInTheDocument();
      expect(screen.queryByTestId("delivery-status-strip-2")).not.toBeInTheDocument();
      expect(screen.getAllByTestId("delivery-status-strip")).toHaveLength(1);
      expect(screen.getByTestId("delivery-status-chip")).toHaveAttribute("data-status", row.chip);
      const body = document.body.textContent?.toLowerCase() ?? "";
      expect(body).not.toMatch(/blocked by tarka|we blocked payout|case queue|case crm/);
      unmount();
    }
  });

  it("help one-liner: delivery reliability ≠ enforcement SKU suite", async () => {
    vi.mocked(client.decisions.getEnforcementDeliveries).mockResolvedValue({
      schema_id: "tarka.enforcement_delivery_query/v1",
      deliveries: [
        {
          trace_id: "tr-login-1",
          tenant_id: "demo",
          action_id: "g".repeat(64),
          attempt_count: 1,
          last_status: "emitted",
          last_error: null,
          acked_at: null,
        },
      ],
    });
    render(wrap(<Decisions />));
    const help = await screen.findByTestId("delivery-status-help");
    expect(help.textContent?.toLowerCase()).toMatch(/delivery reliability/);
    expect(help.textContent?.toLowerCase()).toMatch(/not an enforcement sku suite/);
    expect(help.textContent?.toLowerCase()).not.toMatch(/blocked by tarka|enforcement suite sku/i);
  });
});
