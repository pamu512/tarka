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
    expect(el.textContent || "").not.toMatch(/scorecard|maturity|incumbent|\bOSS\b/i);
    expect(screen.getByTestId("bakeoff-help")).toHaveTextContent(/tenant policy/i);
    expect(screen.getByTestId("bakeoff-help")).toHaveTextContent(/loop metrics/i);
  });

  it("empty labels say no labels yet", () => {
    render(<LoopScoreboard metrics={{ fp_count: 0, fp_cost_sum: 0 }} />);
    expect(screen.getByTestId("loop-scoreboard")).toHaveTextContent("no labels yet");
  });

  it("renders action mix counts when present", () => {
    render(
      <LoopScoreboard
        metrics={{
          action_mix: { allow: 2, deny: 1, flag: 1 },
          evaluate_count: 4,
        }}
      />,
    );
    const mix = screen.getByTestId("loop-action-mix");
    expect(mix).toHaveTextContent("allow 2");
    expect(mix).toHaveTextContent("deny 1");
    expect(mix).toHaveTextContent("flag 1");
    expect(mix.textContent || "").not.toMatch(/0%/);
    expect(screen.getByTestId("loop-scoreboard")).toHaveTextContent(/action mix/i);
  });

  it("null shadow divergence is an em-dash plus reason, not 0%", () => {
    render(
      <LoopScoreboard
        metrics={{
          shadow_divergence: null,
          reason_code: "no_shadow_live_pairs",
          unknown_reasons: { shadow_divergence: "no_shadow_live_pairs" },
        }}
      />,
    );
    const el = screen.getByTestId("loop-shadow-divergence");
    expect(el).toHaveTextContent("—");
    expect(el).toHaveTextContent(/no Observe\/live pairs in window/i);
    expect(el.textContent || "").not.toMatch(/0%/);
  });

  it("null field without reason_code still dashes, never 0%", () => {
    render(<LoopScoreboard metrics={{ shadow_divergence: null }} />);
    const el = screen.getByTestId("loop-shadow-divergence");
    expect(el).toHaveTextContent("—");
    expect(el).toHaveTextContent(/metrics not yet available/i);
    expect(el.textContent || "").not.toMatch(/0%/);
  });

  it("evaluate count shows the number or an honest dash", () => {
    const { rerender } = render(<LoopScoreboard metrics={{ evaluate_count: 7 }} />);
    expect(screen.getByTestId("loop-evaluate-count")).toHaveTextContent("7");

    rerender(
      <LoopScoreboard
        metrics={{
          evaluate_count: null,
          reason_code: "evaluate_store_absent",
          unknown_reasons: { evaluate_count: "evaluate_store_absent" },
        }}
      />,
    );
    const unknown = screen.getByTestId("loop-evaluate-count");
    expect(unknown).toHaveTextContent("—");
    expect(unknown).toHaveTextContent(/no audit in window/i);
    expect(unknown.textContent || "").not.toMatch(/0%/);

    rerender(<LoopScoreboard metrics={{ evaluate_count: 0 }} />);
    expect(screen.getByTestId("loop-evaluate-count")).toHaveTextContent("0");
    expect(screen.getByTestId("loop-evaluate-count").textContent || "").not.toMatch(/—/);
  });

  it("measured zero shadow divergence is 0, not a dash", () => {
    render(<LoopScoreboard metrics={{ shadow_divergence: 0 }} />);
    expect(screen.getByTestId("loop-shadow-divergence")).toHaveTextContent("0");
    expect(screen.getByTestId("loop-shadow-divergence").textContent || "").not.toMatch(/—/);
  });

  it("loading and error use English, not 0%", () => {
    const { rerender } = render(<LoopScoreboard metrics={null} loading />);
    expect(screen.getByTestId("loop-scoreboard")).toHaveTextContent(/loading loop metrics/i);
    expect(screen.getByTestId("loop-scoreboard").textContent || "").not.toMatch(/0%/);

    rerender(<LoopScoreboard metrics={null} error />);
    expect(screen.getByTestId("loop-scoreboard")).toHaveTextContent(/loop metrics unavailable/i);
    expect(screen.getByTestId("loop-scoreboard").textContent || "").not.toMatch(/0%/);
  });

  it("loading hides prior numbers (parent-fed; parent refetches on tenant change)", () => {
    const { rerender } = render(
      <LoopScoreboard metrics={{ evaluate_count: 99, action_mix: { allow: 99 } }} />,
    );
    expect(screen.getByTestId("loop-evaluate-count")).toHaveTextContent("99");
    rerender(<LoopScoreboard metrics={null} loading />);
    const el = screen.getByTestId("loop-scoreboard");
    expect(el).toHaveTextContent(/loading loop metrics/i);
    expect(el.textContent || "").not.toMatch(/99/);
  });
});
