import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { PromoteConfirmDialog, packMetricsOneLiner } from "./PromoteConfirmDialog";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    decisions: {
      ...actual.decisions,
      loopMetrics: vi.fn(),
    },
  };
});

describe("PromoteConfirmDialog pack metrics", () => {
  it("renders pack X metrics from loop-metrics, not another pack", async () => {
    vi.mocked(client.decisions.loopMetrics).mockResolvedValue({
      schema_id: "tarka.loop_metrics/v1",
      pack_metrics: [
        { pack_id: "other", rule_hit_rate: 0.9, shadow_divergence: 0.1 },
        { pack_id: "shadow_payment_probe_v1", rule_hit_rate: 0.5, shadow_divergence: 0.25 },
      ],
    });
    render(
      <PromoteConfirmDialog
        packName="shadow_payment_probe_v1"
        packFile="shadow_payment_probe_v1.json"
        tenantId="acme"
        onCancel={() => undefined}
        onConfirm={() => undefined}
      />,
    );
    await waitFor(() => {
      expect(client.decisions.loopMetrics).toHaveBeenCalledWith("acme");
    });
    expect(await screen.findByTestId("promote-rule-hit-rate")).toHaveTextContent("0.5");
    expect(screen.getByTestId("promote-shadow-divergence")).toHaveTextContent("0.25");
    expect(screen.getByTestId("promote-metrics-oneliner")).toHaveTextContent(/50%/);
    expect(screen.getByTestId("promote-metrics-oneliner")).toHaveTextContent(/25%/);
    expect(screen.getByTestId("promote-metrics-oneliner")).toHaveTextContent(/tenant policy/i);
    expect(screen.queryByText("0.9")).not.toBeInTheDocument();
  });

  it("null metrics stay honest — not fake 0%", async () => {
    vi.mocked(client.decisions.loopMetrics).mockResolvedValue({
      schema_id: "tarka.loop_metrics/v1",
      pack_metrics: [{ pack_id: "pack_a", rule_hit_rate: null, shadow_divergence: null }],
    });
    render(
      <PromoteConfirmDialog packName="pack_a" tenantId="acme" onCancel={() => undefined} onConfirm={() => undefined} />,
    );
    expect(await screen.findByTestId("promote-metrics-oneliner")).toHaveTextContent(/not yet available/i);
    expect(screen.getByTestId("promote-rule-hit-rate")).toHaveTextContent(/not loaded/i);
    expect(screen.getByTestId("promote-pack-metrics")).not.toHaveTextContent("0%");
  });

  it("one-liner template does not invent morals", () => {
    expect(packMetricsOneLiner({ rule_hit_rate: 0.4, shadow_divergence: 0.1 })).toMatch(/40%/);
    expect(packMetricsOneLiner({ rule_hit_rate: 0.4, shadow_divergence: 0.1 })).toMatch(/tenant policy/i);
    expect(packMetricsOneLiner({ rule_hit_rate: null, shadow_divergence: null })).toMatch(/not yet available/i);
    expect(packMetricsOneLiner(null)).not.toMatch(/0%/);
  });
});
