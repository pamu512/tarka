/** @vitest-environment jsdom */

import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, fireEvent, within } from "@testing-library/react";

import { PromoteToProductionModal } from "./PromoteToProductionModal";
import type { HypothesisReport } from "@/types/hypothesis";

const GATE_SUMMARY =
  "This will transition Rule #902 from Observation to Active. Estimated impact: +15% block rate.";

const report: HypothesisReport = {
  report_id: "r-gate-199",
  fingerprint_kind: "canvas_hash",
  fingerprint_value: "ch_abc",
  distinct_account_count: 12,
  suggested_rule: {
    id: "shadow_rule_902",
    metadata: { rule_number: 902, is_shadow: true, mode: "observation" },
  },
};

describe("PromoteToProductionModal", () => {
  afterEach(() => {
    cleanup();
  });

  it("gate 199: two-step flow shows final impact summary on confirm step", () => {
    render(
      <PromoteToProductionModal
        open
        report={report}
        estimatedBlockRateImpactPct={15}
        onClose={vi.fn()}
        onConfirmPromote={vi.fn()}
      />,
    );

    const modal = screen.getByTestId("promote-to-production-modal");
    expect(within(modal).getByText(/step 1 of 2/i)).toBeTruthy();
    expect(screen.queryByTestId("promote-final-summary")).toBeNull();

    fireEvent.click(screen.getByTestId("promote-step-continue"));
    expect(within(modal).getByText(/step 2 of 2/i)).toBeTruthy();
    expect(screen.getByTestId("promote-final-summary").textContent).toBe(GATE_SUMMARY);
  });

  it("invokes onConfirmPromote when production CTA clicked", () => {
    const onConfirm = vi.fn();
    render(
      <PromoteToProductionModal
        open
        report={report}
        estimatedBlockRateImpactPct={15}
        onClose={vi.fn()}
        onConfirmPromote={onConfirm}
      />,
    );

    fireEvent.click(screen.getByTestId("promote-step-continue"));
    fireEvent.click(screen.getByTestId("promote-confirm"));
    expect(onConfirm).toHaveBeenCalledWith(report);
  });
});
