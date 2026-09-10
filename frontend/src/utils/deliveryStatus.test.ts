import { describe, expect, it } from "vitest";

import { resolveDeliveryStatus } from "./deliveryStatus";

describe("resolveDeliveryStatus", () => {
  it("maps inbound product ACK to acked when the webhook plane is on", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: true,
      journalStatus: "acked",
      productAck: { status: "applied" },
      enforcementMode: "emit_only",
    });
    expect(view.chip).toBe("acked");
    expect(view.label).toBe("acked");
    expect(view.hint.toLowerCase()).not.toMatch(/blocked payout|promote|demote|case queue|crm/i);
  });

  it("maps HTTP 2xx journal without product ACK to emitted", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: true,
      journalStatus: "acked",
      productAck: null,
      enforcementMode: "emit_only",
    });
    expect(view.chip).toBe("emitted");
    expect(view.label).toBe("emitted");
    expect(view.hint.toLowerCase()).toMatch(/advisory emit/);
    expect(view.hint.toLowerCase()).not.toMatch(/blocked payout/);
  });

  it("maps journal error / non_2xx to failed", () => {
    const err = resolveDeliveryStatus({
      webhookConfigured: true,
      journalStatus: "error",
      productAck: null,
    });
    const non2xx = resolveDeliveryStatus({
      webhookConfigured: true,
      journalStatus: "non_2xx",
      productAck: null,
    });
    expect(err.chip).toBe("failed");
    expect(err.label).toBe("failed");
    expect(non2xx.chip).toBe("failed");
    expect(non2xx.label).toBe("failed");
  });

  it("empty webhook URL is not configured, never fake acked", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: false,
      journalStatus: "skipped",
      productAck: { status: "applied" },
      enforcementMode: "emit_only",
    });
    expect(view.chip).toBe("not_configured");
    expect(view.label).toBe("not configured");
    expect(view.chip).not.toBe("acked");
    expect(view.hint.toLowerCase()).toMatch(/plane off|not configured|empty/);
    expect(view.hint.toLowerCase()).not.toMatch(/blocked payout|we blocked/);
  });

  it("journal skipped / webhook_unset is not configured", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: true,
      journalStatus: "skipped",
      journalReason: "webhook_unset",
      productAck: null,
    });
    expect(view.chip).toBe("not_configured");
    expect(view.label).toBe("not configured");
  });

  it("maps D9.3 last_status retrying to retrying, not failed", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: true,
      lastStatus: "retrying",
      journalStatus: "error",
      productAck: null,
      enforcementMode: "emit_only",
    });
    expect(view.chip).toBe("retrying");
    expect(view.label).toBe("retrying");
    expect(view.chip).not.toBe("failed");
    expect(view.hint.toLowerCase()).toMatch(/advisory emit/);
    expect(view.hint.toLowerCase()).not.toMatch(/blocked by tarka|we blocked|blocked payout/);
  });

  it("maps D9.3 last_status dead_lettered to dead_lettered, not failed", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: true,
      lastStatus: "dead_lettered",
      journalStatus: "non_2xx",
      productAck: null,
      enforcementMode: "emit_only",
    });
    expect(view.chip).toBe("dead_lettered");
    expect(view.label).toBe("dead lettered");
    expect(view.chip).not.toBe("failed");
    expect(view.hint.toLowerCase()).toMatch(/not demote|not a demote/);
    expect(view.hint.toLowerCase()).not.toMatch(/blocked by tarka|auto-demote|we blocked/);
  });

  it("keeps residual failed only for unclassified journal error", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: true,
      lastStatus: "error",
      journalStatus: "error",
      productAck: null,
    });
    expect(view.chip).toBe("failed");
    expect(view.label).toBe("failed");
  });

  it("empty webhook URL with D9.3 acked is not configured, never fake acked", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: false,
      lastStatus: "acked",
      productAck: { status: "applied" },
      enforcementMode: "emit_only",
    });
    expect(view.chip).toBe("not_configured");
    expect(view.chip).not.toBe("acked");
    expect(view.hint.toLowerCase()).not.toMatch(/blocked by tarka|we blocked/);
  });

  it("emit_only copy is advisory emit, not blocked by Tarka", () => {
    for (const lastStatus of ["emitted", "retrying", "dead_lettered", "acked"]) {
      const view = resolveDeliveryStatus({
        webhookConfigured: true,
        lastStatus,
        productAck: lastStatus === "acked" ? { status: "applied" } : null,
        enforcementMode: "emit_only",
      });
      expect(view.hint.toLowerCase()).not.toMatch(/blocked by tarka|we blocked payout|blocked payout/);
      expect(view.hint.toLowerCase()).toMatch(/advisory emit|plane off|not configured/);
    }
  });

  it("help one-liner says delivery reliability is not an enforcement SKU suite", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: true,
      lastStatus: "emitted",
      enforcementMode: "emit_only",
    });
    expect(view.hint.toLowerCase()).toMatch(/delivery reliability/);
    expect(view.hint.toLowerCase()).toMatch(/not an enforcement sku suite/);
  });
});
