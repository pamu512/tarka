/** @vitest-environment jsdom */

import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, fireEvent, waitFor, within } from "@testing-library/react";

import { HypothesisCard } from "./HypothesisCard";
import type { HypothesisReport } from "@/types/hypothesis";

const GATE_NARRATIVE =
  "A potential botnet is using a spoofed iPhone 15 fingerprint. 50 accounts created in 2 hours.";

const sampleReport: HypothesisReport = {
  report_id: "r-gate-197",
  fingerprint_kind: "canvas_hash",
  fingerprint_value: "canvas_hash_999_xyz",
  distinct_account_count: 50,
  saarthi_narrative: GATE_NARRATIVE,
  analyst_suggestion_allowed: true,
  backtest_false_positive_rate: 0.0005,
};

describe("HypothesisCard", () => {
  afterEach(() => {
    cleanup();
  });

  it("gate 197: shows Saarthi narrative and potential savings with high-contrast impact", () => {
    render(
      <HypothesisCard
        report={sampleReport}
        potentialSavings={284_500}
        onStartObservation={vi.fn()}
      />,
    );

    expect(screen.getByTestId("hypothesis-saarthi-narrative").textContent).toContain(
      GATE_NARRATIVE,
    );
    expect(screen.getByTestId("hypothesis-potential-savings").textContent).toMatch(/284/);
    expect(screen.getByRole("button", { name: /start observation/i })).toBeTruthy();
  });

  it("shows Promote after observation is active and opens guardrail summary", () => {
    const reportWithRule: HypothesisReport = {
      ...sampleReport,
      suggested_rule: {
        id: "shadow_rule_902",
        metadata: { rule_number: 902, is_shadow: true, mode: "observation" },
      },
    };
    render(
      <HypothesisCard
        report={reportWithRule}
        potentialSavings={10_000}
        observationState="active"
        onPromoteToProduction={vi.fn()}
        estimatedBlockRateImpactPct={15}
      />,
    );

    fireEvent.click(screen.getByTestId("hypothesis-promote"));
    fireEvent.click(screen.getByTestId("promote-step-continue"));
    expect(screen.getByTestId("promote-final-summary").textContent).toContain("Rule #902");
    expect(screen.getByTestId("promote-final-summary").textContent).toContain("+15%");
  });

  it("invokes onStartObservation when CTA clicked", async () => {
    const onStart = vi.fn().mockResolvedValue(undefined);
    render(
      <HypothesisCard report={sampleReport} potentialSavings={10_000} onStartObservation={onStart} />,
    );

    const card = screen.getByTestId("hypothesis-card");
    fireEvent.click(within(card).getByTestId("hypothesis-start-observation"));
    await waitFor(() => {
      expect(onStart).toHaveBeenCalledWith(sampleReport);
    });
  });
});
