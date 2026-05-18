import { describe, expect, it } from "vitest";
import { translateOp } from "./ast-translator";

describe("translateOp", () => {
  it('maps gt + velocity_1h to the hourly transactions sentence (Prompt 143 gate)', () => {
    expect(translateOp("gt", "velocity_1h", 5)).toBe("exceeded the hourly limit of 5 transactions.");
  });

  it("uses semantic label for graph_score", () => {
    const s = translateOp("eq", "graph_score", 0.72);
    expect(s).toContain("Network Risk Level");
    expect(s).toContain("0.72");
  });
});
