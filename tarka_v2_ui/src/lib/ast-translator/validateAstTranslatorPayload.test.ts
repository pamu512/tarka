import { describe, expect, it } from "vitest";

import {
  extractJsonObject,
  parseAstTranslatorPayload,
  parseGeminiAstTranslatorText,
} from "./validateAstTranslatorPayload";

describe("parseAstTranslatorPayload", () => {
  it("accepts valid humanReason and badges", () => {
    const out = parseAstTranslatorPayload({
      humanReason: "First sentence here. Second sentence follows.",
      badges: ["High Risk", "policy_hit", "Velocity Spike"],
    });
    expect(out?.humanReason).toContain("First sentence");
    expect(out?.badges).toHaveLength(3);
  });

  it("rejects fewer than 3 badges", () => {
    expect(
      parseAstTranslatorPayload({
        humanReason: "One. Two.",
        badges: ["a", "b"],
      }),
    ).toBeNull();
  });
});

describe("parseGeminiAstTranslatorText", () => {
  it("parses fenced JSON", () => {
    const text = '\n```json\n{"humanReason":"A. B.","badges":["x","y","z"]}\n```\n';
    const out = parseGeminiAstTranslatorText(text);
    expect(out?.badges).toEqual(["x", "y", "z"]);
  });

  it("extractJsonObject handles bare object", () => {
    expect(extractJsonObject('prefix {"humanReason":"A. B.","badges":["a","b","c"]} suffix')).toContain(
      "humanReason",
    );
  });
});
