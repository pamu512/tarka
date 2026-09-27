import { describe, it, expect } from "vitest";
import { emptyPackDraft, EVALUATOR_OPS, WIDGET_OPS } from "./uiPack";

describe("uiPack", () => {
  it("creates codec v1 empty draft", () => {
    const d = emptyPackDraft();
    expect(d.codecVersion).toBe(1);
    expect(d.rules).toEqual([]);
    expect(d.rawTopLevel).toEqual([]);
  });
  it("op registry matches the evaluator surface", () => {
    expect(WIDGET_OPS).toHaveLength(9);
    expect(EVALUATOR_OPS).toHaveLength(16);
    expect(EVALUATOR_OPS).toContain("starts_with");
    expect(EVALUATOR_OPS).toContain("not_exists");
  });
});
