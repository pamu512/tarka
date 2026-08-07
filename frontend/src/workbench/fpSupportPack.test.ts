import { describe, expect, it } from "vitest";
import { FP_SUPPORT_PACK_LABEL, buildFpSupportPackPayload } from "./fpSupportPack";

describe("fpSupportPack", () => {
  it("builds comment body and label", () => {
    const p = buildFpSupportPackPayload({
      summaryMarkdown: "## Support-safe case summary\n\nCase ID: c1\n",
      actor: "analyst-a",
    });
    expect(p.label).toBe(FP_SUPPORT_PACK_LABEL);
    expect(p.author).toBe("analyst-a");
    expect(p.body).toContain("Support-safe case summary");
    expect(p.body).toContain("Case ID: c1");
  });
});
