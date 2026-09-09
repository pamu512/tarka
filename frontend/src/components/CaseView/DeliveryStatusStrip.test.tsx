import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DeliveryStatusStrip } from "./DeliveryStatusStrip";
import { resolveDeliveryStatus } from "../../utils/deliveryStatus";

describe("DeliveryStatusStrip", () => {
  it("renders emitted / acked / failed / not configured chips", () => {
    const cases = [
      {
        chip: "emitted" as const,
        input: { webhookConfigured: true, journalStatus: "acked" as const, productAck: null },
      },
      {
        chip: "acked" as const,
        input: {
          webhookConfigured: true,
          journalStatus: "acked" as const,
          productAck: { status: "applied" },
        },
      },
      {
        chip: "failed" as const,
        input: { webhookConfigured: true, journalStatus: "error" as const, productAck: null },
      },
      {
        chip: "not_configured" as const,
        input: { webhookConfigured: false, journalStatus: "skipped" as const, productAck: null },
      },
    ];
    for (const { chip, input } of cases) {
      const view = resolveDeliveryStatus({ ...input, enforcementMode: "emit_only" });
      const { unmount } = render(<DeliveryStatusStrip view={view} />);
      const el = screen.getByTestId("delivery-status-chip");
      expect(el).toHaveAttribute("data-status", chip);
      expect(el.textContent?.toLowerCase()).toContain(
        chip === "not_configured" ? "not configured" : chip,
      );
      const strip = screen.getByTestId("delivery-status-strip");
      expect(strip.textContent?.toLowerCase()).not.toMatch(/blocked payout|promote|demote|case crm/i);
      unmount();
    }
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
