import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LoopScoreboard } from "./LoopScoreboard";

describe("LoopScoreboard", () => {
  it("renders numbers only", () => {
    render(
      <LoopScoreboard
        metrics={{
          leftover_to_draft_ms: { p50: 200 },
          drafts_to_observe: { human: 2, ai: 1 },
          ai_backtest_block_rate: 0.5,
          fp_count: 3,
          fp_cost_sum: 12.5,
          label_latency_ms: { p50: 5000 },
          promote_ttl_ms: { p50: 10000 },
        }}
      />,
    );
    const el = screen.getByTestId("loop-scoreboard");
    expect(el).toHaveTextContent("200");
    expect(el).toHaveTextContent("human 2 / AI 1");
    expect(el).toHaveTextContent("50%");
    expect(el).toHaveTextContent("3 / 13");
    expect(el.textContent || "").not.toMatch(/case|inbox|CRM/i);
  });
});
