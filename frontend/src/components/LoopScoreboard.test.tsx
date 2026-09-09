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
    expect(screen.getByTestId("bakeoff-help")).toHaveTextContent(/tenant policy/i);
  });

  it("empty labels say no labels yet", () => {
    render(<LoopScoreboard metrics={{ fp_count: 0, fp_cost_sum: 0 }} />);
    expect(screen.getByTestId("loop-scoreboard")).toHaveTextContent("no labels yet");
  });

  it("shows join rate and labeled receipt rate when present", () => {
    render(
      <LoopScoreboard
        metrics={{
          join_rate: 0.5,
          labeled_receipt_rate: 0.5,
        }}
      />,
    );
    const join = screen.getByTestId("loop-join-rate");
    const labeled = screen.getByTestId("loop-labeled-receipt-rate");
    expect(join).toHaveTextContent("50%");
    expect(labeled).toHaveTextContent("50%");
    expect(join.textContent || "").not.toMatch(/—/);
    expect(screen.getByTestId("bakeoff-help")).toHaveTextContent(/effectiveness/i);
    expect(screen.getByTestId("bakeoff-help")).toHaveTextContent(/not a CRM/i);
    expect(screen.getByTestId("bakeoff-help")).toHaveTextContent(/tenant policy/i);
  });

  it("null join rate is an em-dash plus reason, not 0%", () => {
    render(
      <LoopScoreboard
        metrics={{
          join_rate: null,
          labeled_receipt_rate: null,
          unknown_reasons: {
            join_rate: "no_labels",
            labeled_receipt_rate: "no_labels",
          },
        }}
      />,
    );
    const join = screen.getByTestId("loop-join-rate");
    expect(join).toHaveTextContent("—");
    expect(join).toHaveTextContent(/no labels/i);
    expect(join.textContent || "").not.toMatch(/0%/);
    const labeled = screen.getByTestId("loop-labeled-receipt-rate");
    expect(labeled).toHaveTextContent("—");
    expect(labeled.textContent || "").not.toMatch(/0%/);
  });
});
