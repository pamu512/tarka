import { describe, expect, it } from "vitest";
import { buildSupportSafeSummary } from "./supportSafeSummary";

describe("buildSupportSafeSummary", () => {
  it("includes safe fields and never-share section", () => {
    const text = buildSupportSafeSummary({
      caseId: "c1",
      tenantId: "demo",
      entityId: "e1",
      traceId: "t1",
      status: "resolved",
      labels: ["disposition:FALSE_POSITIVE"],
      decisionExplain: {
        score: 12,
        decision: "review",
        reasons: [],
        tags: ["sdk:ok"],
        rule_hits: ["velocity_guard"],
        recommended_action: "soft_challenge",
        inference_context: null,
      },
    });
    expect(text).toContain("Case ID: c1");
    expect(text).toContain("Disposition reason: FALSE_POSITIVE");
    expect(text).toContain("Rule hits: velocity_guard");
    expect(text).toContain("Do not share");
    expect(text).not.toContain("evaluate_payload");
  });
});
