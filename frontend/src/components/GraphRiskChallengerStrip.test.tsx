import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GraphRiskChallengerStrip } from "./GraphRiskChallengerStrip";

describe("GraphRiskChallengerStrip", () => {
  it("shows readiness without GNN live claim", () => {
    render(
      <GraphRiskChallengerStrip
        data={{
          display_name: "Graph-risk / Ring-score challenger",
          subtitle: "mp-logreg holdout-gated · baseline heuristic_v1",
          graph_hop: "off",
          overlay_url: "empty",
          state: "collecting",
          trainable_rows: 2,
          labeled_rows: 4,
          labeled_pct: 0.4,
          trainable_pct: 0.5,
          ready_to_train: false,
          bars: { min_trainable_rows: 8 },
          last_gate: { serve_allowed: null },
          gnn_claim_allowed: false,
          live_effect: "pack_promote_only",
          note: "Empty overlay URL is evaluate-only.",
        }}
      />,
    );
    const el = screen.getByTestId("graph-risk-challenger");
    expect(el).toHaveTextContent("Graph-risk / Ring-score challenger");
    expect(el).toHaveTextContent("empty");
    expect(el).toHaveTextContent("pack_promote_only");
    expect(el.textContent || "").not.toMatch(/\bGNN live\b/i);
  });
});
