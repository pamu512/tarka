/** @vitest-environment jsdom */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { DecisionSummary } from "./DecisionSummary";

/** Prompt 144 gate — analyst sees narrative, not raw graph_score floats in the UI. */
const GATE_NARRATIVE =
  "Suspected Sybil Attack: Device shared across multiple high-risk identities";

describe("DecisionSummary", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ summary: GATE_NARRATIVE }),
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('gate 144: displays the Saarthi sentence, not raw graph scores', async () => {
    const execution_trace = {
      graph_context: { graph_score: 0.942, sybil_links: 7 },
      enforcement: { raw_graph_score: 0.942 },
    };

    render(<DecisionSummary execution_trace={execution_trace} autoGenerate />);

    await waitFor(() => {
      const el = screen.getByTestId("saarthi-decision-summary");
      expect(el.textContent ?? "").toContain(GATE_NARRATIVE);
    });

    expect(screen.queryByText(/0\.942/)).toBeNull();
    expect(screen.queryByText(/graph_score/)).toBeNull();
  });
});
