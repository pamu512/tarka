import { describe, expect, it } from "vitest";

import {
  fallbackHypothesisNarrative,
  normalizeTwoSentenceNarrative,
} from "./hypothesisNarrativePrompt";

/** Prompt 195 gate — 50 canvas-hash hits in ~2 hours. */
describe("hypothesisNarrativePrompt", () => {
  it("gate 195: fallback mentions 50 accounts and 2 hours", () => {
    const narrative = fallbackHypothesisNarrative({
      fingerprint_kind: "canvas_hash",
      fingerprint_value: "canvas_hash_999_xyz",
      distinct_account_count: 50,
      window_hours_elapsed: 2,
    });
    expect(normalizeTwoSentenceNarrative(narrative)).toBe(narrative);
    expect(narrative).toContain("50 accounts");
    expect(narrative).toContain("2 hours");
    expect(narrative.toLowerCase()).toContain("botnet");
  });
});
