import { describe, expect, it } from "vitest";
import {
  GATE_RULE_BUILDER_BLOCKS,
  GATE_RULE_BUILDER_JSON,
  compileBlocksToRootNode,
} from "@/lib/compile-rule-ast";

describe("compileBlocksToRootNode", () => {
  it("matches the rule-engine AndNode schema for the Prompt gate", () => {
    const out = compileBlocksToRootNode(GATE_RULE_BUILDER_BLOCKS);
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    expect(out.root).toEqual(GATE_RULE_BUILDER_JSON);
  });

  it("rejects GT with non-numeric value", () => {
    const out = compileBlocksToRootNode([
      {
        id: "a",
        field: "amount",
        operator: "GT",
        valueRaw: "oops",
      },
    ]);
    expect(out.ok).toBe(false);
  });
});
