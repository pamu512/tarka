import { describe, it, expect } from "vitest";
import flat from "../fixtures/flat-when.json";
import flatExt from "../fixtures/flat-when-extended-op.json";
import hop from "../fixtures/when-ast-hop.json";
import tagRules from "../fixtures/tag-rules.json";
import bothSet from "../fixtures/when-and-when-ast.json";
import { validatePackJson } from "./validatePack";

describe("validatePackJson", () => {
  it("accepts a server-normalized flat when[] pack", () => {
    expect(validatePackJson(flat)).toEqual({ ok: true });
  });

  it("accepts starts_with (op is open)", () => {
    expect(validatePackJson(flatExt)).toEqual({ ok: true });
  });

  it("accepts when_ast hop and tag_rules and both-set fixtures", () => {
    expect(validatePackJson(hop)).toEqual({ ok: true });
    expect(validatePackJson(tagRules)).toEqual({ ok: true });
    expect(validatePackJson(bothSet)).toEqual({ ok: true });
  });

  it("rejects a pack missing required fields", () => {
    const broken = { version: 1, rules: [] };
    const result = validatePackJson(broken);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.some((e) => e.includes("name"))).toBe(true);
    }
  });
});
