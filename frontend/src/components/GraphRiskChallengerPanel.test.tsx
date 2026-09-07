import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  decisions: {
    graphRiskExport: vi.fn(),
    graphRiskTrain: vi.fn(),
    graphRiskEnableShadow: vi.fn(),
    graphRiskRetire: vi.fn(),
  },
}));

import { GraphRiskChallengerPanel } from "./GraphRiskChallengerPanel";

describe("GraphRiskChallengerPanel", () => {
  it("disables Enable shadow until serve_allowed", () => {
    render(
      <GraphRiskChallengerPanel
        tenantId="demo"
        data={{
          display_name: "Graph-risk / Ring-score challenger",
          last_gate: { serve_allowed: false },
          live_effect: "pack_promote_only",
        }}
        onRefresh={() => undefined}
      />,
    );
    const btn = screen.getByRole("button", { name: /Enable shadow URL/i });
    expect(btn).toBeDisabled();
    expect(screen.getByTestId("graph-risk-challenger-panel").textContent || "").not.toMatch(
      /\bGNN live\b/i,
    );
  });
});
