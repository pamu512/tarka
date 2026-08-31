import { describe, expect, it } from "vitest";
import { formatLiveRuleSlipLine } from "./liveRuleSlip";

describe("formatLiveRuleSlipLine", () => {
  it("ping only when no draft", () => {
    expect(
      formatLiveRuleSlipLine({
        rule_id: "r1",
        triggers: ["fire_rate"],
        hypothesis: "underpowered",
        parked_draft: null,
      }),
    ).toBe("r1 · fire_rate · underpowered · ping only");
  });
  it("names parked draft", () => {
    expect(
      formatLiveRuleSlipLine({
        rule_id: "r1",
        triggers: ["mix"],
        hypothesis: "successor",
        parked_draft: "slip_successor_r1",
      }),
    ).toBe("r1 · mix · successor · slip_successor_r1");
  });
});
