import { describe, expect, it } from "vitest";

import { parseAiReasoning, splitReasoningString } from "./parse-ai-reasoning";

describe("splitReasoningString", () => {
  it("splits markdown bullet lines", () => {
    const raw = `- Velocity spike on device\n- Shared IP with blocked node\n- Amount above cohort median`;
    expect(splitReasoningString(raw)).toEqual([
      "Velocity spike on device",
      "Shared IP with blocked node",
      "Amount above cohort median",
    ]);
  });

  it("splits numbered lists", () => {
    const raw = `1. First signal\n2. Second signal`;
    expect(splitReasoningString(raw)).toEqual(["First signal", "Second signal"]);
  });

  it("falls back to paragraph breaks then single newlines", () => {
    expect(splitReasoningString("Line one\n\nLine two")).toEqual(["Line one", "Line two"]);
    expect(splitReasoningString("Alpha\nBeta")).toEqual(["Alpha", "Beta"]);
  });

  it("returns one chunk for a single-line narrative", () => {
    const one = "Linked to Blocked Node: device overlap with prior fraud case.";
    expect(splitReasoningString(one)).toEqual([one]);
  });
});

describe("parseAiReasoning", () => {
  it("parses production Shadow markdown string into steps", () => {
    const raw =
      "- **Linked to Blocked Node** on shared hardware.\n- Velocity window exceeded for this MCC.\n- Recommend SHADOW_REVIEW pending analyst confirmation.";
    const steps = parseAiReasoning(raw);
    expect(steps.length).toBe(3);
    expect(steps[0]?.heading).toContain("Linked to Blocked Node");
    expect(steps[0]?.body).toContain("shared hardware");
    expect(steps[2]?.body).toContain("SHADOW_REVIEW");
  });

  it("maps legacy array of strings", () => {
    const steps = parseAiReasoning([
      "Initial cohort within baseline.",
      "Geo mismatch adds weight.",
    ]);
    expect(steps).toHaveLength(2);
    expect(steps[0]?.heading).toContain("Initial cohort");
  });

  it("maps structured { step, detail } objects", () => {
    const steps = parseAiReasoning([
      { step: "Feature cross-check", detail: "BIN geography diverges from cardholder region." },
      { step: "Policy synthesis", detail: "Rules engine suggested FLAG." },
    ]);
    expect(steps).toHaveLength(2);
    expect(steps[0]?.heading).toBe("Feature cross-check");
    expect(steps[0]?.body).toBe("BIN geography diverges from cardholder region.");
    expect(steps[1]?.heading).toBe("Policy synthesis");
  });

  it("returns empty for null, undefined, and blank string", () => {
    expect(parseAiReasoning(null)).toEqual([]);
    expect(parseAiReasoning(undefined)).toEqual([]);
    expect(parseAiReasoning("   \n  ")).toEqual([]);
  });

  it("returns empty for non-array non-string input", () => {
    expect(parseAiReasoning({ foo: "bar" })).toEqual([]);
  });
});
