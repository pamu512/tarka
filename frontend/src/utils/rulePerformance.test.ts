import { describe, expect, it } from "vitest";

import {
  aggregateRuleOutcomes,
  filterRulesByEngine,
  isRustStyleRuleId,
  topByDeny,
  topByReview,
} from "./rulePerformance";

describe("aggregateRuleOutcomes", () => {
  it("attributes deny vs review per firing rule", () => {
    const rows = aggregateRuleOutcomes([
      { decision: "deny", rule_hits: ["rs_a", "rs_b"] },
      { decision: "review", rule_hits: ["rs_a"] },
      { decision: "allow", rule_hits: ["json_x"] },
    ]);
    const byId = Object.fromEntries(rows.map((r) => [r.rule_id, r]));
    expect(byId.rs_a?.deny_count).toBe(1);
    expect(byId.rs_a?.review_count).toBe(1);
    expect(byId.rs_b?.deny_count).toBe(1);
    expect(byId.json_x?.allow_count).toBe(1);
  });
});

describe("isRustStyleRuleId", () => {
  it("detects rs_ and path-like ids", () => {
    expect(isRustStyleRuleId("rs_velocity_cap")).toBe(true);
    expect(isRustStyleRuleId("tarka_core::aml_block")).toBe(true);
    expect(isRustStyleRuleId("velocity_guard")).toBe(false);
  });
});

describe("filterRulesByEngine", () => {
  it("keeps only rust-style ids when rustOnly", () => {
    const rows = aggregateRuleOutcomes([
      { decision: "deny", rule_hits: ["rs_one"] },
      { decision: "review", rule_hits: ["soft_velocity"] },
    ]);
    const f = filterRulesByEngine(rows, true);
    expect(f.map((r) => r.rule_id)).toEqual(["rs_one"]);
  });
});

describe("top helpers", () => {
  it("orders by deny and review", () => {
    const rows = aggregateRuleOutcomes([
      { decision: "deny", rule_hits: ["r1"] },
      { decision: "deny", rule_hits: ["r1"] },
      { decision: "deny", rule_hits: ["r2"] },
      { decision: "review", rule_hits: ["r3"] },
      { decision: "review", rule_hits: ["r3"] },
      { decision: "review", rule_hits: ["r3"] },
      { decision: "review", rule_hits: ["r2"] },
    ]);
    expect(topByDeny(rows, 1)[0]?.rule_id).toBe("r1");
    const reviews = topByReview(rows, 2);
    expect(reviews[0]?.rule_id).toBe("r3");
  });
});
