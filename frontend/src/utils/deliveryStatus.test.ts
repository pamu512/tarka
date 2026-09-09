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
});
