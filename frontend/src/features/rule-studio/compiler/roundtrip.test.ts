/**
 * Round-trip identity against server-normalized fixtures.
 *
 * Intentional normalizations (document here if added):
 * - Condition row `id` is draft-only; stripped on compile (wire has no cond ids).
 * - `enabled` is never on wire packs (frontend-only).
 * - Key order within objects is not significant for deep equality.
 * - Missing rule id → compile emits deterministic studio_<slug>_<hash>.
 * - Post-save: callers must rehydrate from server-returned pack (ids/defaults/nulls).
 */
import { describe, it, expect } from "vitest";
import flat from "../fixtures/flat-when.json";
import flatExt from "../fixtures/flat-when-extended-op.json";
import hop from "../fixtures/when-ast-hop.json";
import bothSet from "../fixtures/when-and-when-ast.json";
import tagRules from "../fixtures/tag-rules.json";
import { parsePack } from "./parsePack";
import { compilePack } from "./compilePack";

describe("roundtrip", () => {
  it("flat when[] parse∘compile preserves the normalized pack", () => {
    const draft = parsePack(flat);
    expect(compilePack(draft)).toEqual(flat);
  });

  it("re-parse of compile is idempotent", () => {
    const once = parsePack(flat);
    const twice = parsePack(compilePack(once));
    expect(twice).toEqual(once);
  });

  it("deep when_ast becomes RawBlock and re-emits byte-preserved", () => {
    const draft = parsePack(hop);
    expect(draft.rules.some((r) => r.rawBlocks.length > 0)).toBe(true);
    expect(compilePack(draft)).toEqual(hop);
  });

  it("both-set when+when_ast rule is a whole-rule RawBlock", () => {
    const draft = parsePack(bothSet);
    expect(
      draft.rules.some((r) => r.rawBlocks.some((b) => b.kind === "both_set_rule")),
    ).toBe(true);
    expect(compilePack(draft)).toEqual(bothSet);
  });

  it("non-widget op (starts_with) stays an editable condition row", () => {
    const draft = parsePack(flatExt);
    expect(draft.rules[0].when[0].op).toBe("starts_with");
    expect(draft.rules[0].rawBlocks).toHaveLength(0);
  });

  it("tag_rules pack round-trips", () => {
    expect(compilePack(parsePack(tagRules))).toEqual(tagRules);
  });
});
