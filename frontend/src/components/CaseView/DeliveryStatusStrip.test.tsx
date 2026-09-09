import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DeliveryStatusStrip } from "./DeliveryStatusStrip";
import { resolveDeliveryStatus } from "../../utils/deliveryStatus";

describe("DeliveryStatusStrip", () => {
  it("renders emitted / retrying / dead_lettered / acked / not configured chips", () => {
    const cases = [
      {
        chip: "emitted" as const,
        input: { webhookConfigured: true, lastStatus: "emitted" },
      },
      {
        chip: "retrying" as const,
        input: { webhookConfigured: true, lastStatus: "retrying" },
      },
      {
        chip: "dead_lettered" as const,
        input: { webhookConfigured: true, lastStatus: "dead_lettered" },
      },
      {
        chip: "acked" as const,
        input: {
          webhookConfigured: true,
          lastStatus: "acked",
          productAck: { status: "applied" },
        },
      },
      {
        chip: "not_configured" as const,
        input: { webhookConfigured: false, lastStatus: "acked", productAck: { status: "applied" } },
      },
    ];
    for (const { chip, input } of cases) {
      const view = resolveDeliveryStatus({ ...input, enforcementMode: "emit_only" });
      const { unmount } = render(<DeliveryStatusStrip view={view} />);
      const el = screen.getByTestId("delivery-status-chip");
      expect(el).toHaveAttribute("data-status", chip);
      const label =
        chip === "not_configured" ? "not configured" : chip === "dead_lettered" ? "dead lettered" : chip;
      expect(el.textContent?.toLowerCase()).toContain(label);
      const strip = screen.getByTestId("delivery-status-strip");
      expect(strip.textContent?.toLowerCase()).not.toMatch(
        /blocked by tarka|we blocked|blocked payout|case crm|auto-demote/i,
      );
      if (chip === "dead_lettered") {
        expect(el).not.toHaveTextContent(/^failed$/i);
      }
      unmount();
    }
  });

  it("residual failed chip is only for unclassified error, not beside dead_lettered", () => {
    const failed = resolveDeliveryStatus({
      webhookConfigured: true,
      lastStatus: "error",
      enforcementMode: "emit_only",
    });
    const dlq = resolveDeliveryStatus({
      webhookConfigured: true,
      lastStatus: "dead_lettered",
      journalStatus: "error",
      enforcementMode: "emit_only",
    });
    const { unmount } = render(<DeliveryStatusStrip view={failed} />);
    expect(screen.getByTestId("delivery-status-chip")).toHaveAttribute("data-status", "failed");
    unmount();
    render(<DeliveryStatusStrip view={dlq} />);
    expect(screen.getByTestId("delivery-status-chip")).toHaveAttribute("data-status", "dead_lettered");
    expect(screen.getByTestId("delivery-status-chip")).not.toHaveTextContent(/^failed$/i);
  });

  it("help one-liner is delivery reliability, not an enforcement SKU suite", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: true,
      lastStatus: "emitted",
      enforcementMode: "emit_only",
    });
    render(<DeliveryStatusStrip view={view} />);
    const help = screen.getByTestId("delivery-status-help");
    expect(help.textContent?.toLowerCase()).toMatch(/delivery reliability/);
    expect(help.textContent?.toLowerCase()).toMatch(/not an enforcement sku suite/);
    expect(help.textContent?.toLowerCase()).not.toMatch(/blocked by tarka|case queue|crm/i);
  });

  it("empty URL chip is not configured, not acked", () => {
    const view = resolveDeliveryStatus({
      webhookConfigured: false,
      productAck: { status: "applied" },
      enforcementMode: "emit_only",
    });
    render(<DeliveryStatusStrip view={view} />);
    const el = screen.getByTestId("delivery-status-chip");
    expect(el).toHaveAttribute("data-status", "not_configured");
    expect(el).toHaveTextContent(/not configured/i);
    expect(el).not.toHaveTextContent(/^acked$/i);
    expect(screen.getByTestId("delivery-status-strip").textContent?.toLowerCase()).not.toMatch(
      /we blocked|blocked payout/,
    );
  });
});
