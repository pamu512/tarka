import { describe, expect, it } from "vitest";

import { emitHopPack, emitVelocityPack } from "./sentencePack";

describe("sentencePack", () => {
  it("emits Observe JSON for a velocity sentence using a canonical key", () => {
    const pack = emitVelocityPack({ field: "event_count_1h", op: "gte", value: 20 });
    expect(pack.mode).toBe("shadow");
    const rule = (pack.rules as Array<{ when: Array<{ field: string }> }>)[0];
    expect(rule.when[0].field).toBe("event_count_1h");
  });

  it("share-edge emits has_etype without FLAG or sibling claim", () => {
    const pack = emitHopPack({ etype: "USES_DEVICE", kind: "share" });
    const rule = (
      pack.rules as Array<{
        when_ast: { atom?: string; etype?: string };
        tags: string[];
        description: string;
      }>
    )[0];
    expect(rule.when_ast.atom).toBe("has_etype");
    expect(rule.when_ast.etype).toBe("USES_DEVICE");
    expect(rule.tags).not.toContain("FLAG");
    expect(rule.description.toLowerCase()).not.toContain("sibling");
    expect(pack.mode).toBe("shadow");
  });

  it("trust FLAG emits sibling_prior_flag AND and a FLAG tag", () => {
    const pack = emitHopPack({ etype: "USES_DEVICE", kind: "trust" });
    const rule = (
      pack.rules as Array<{
        when_ast: { type: string; children?: Array<Record<string, unknown>> };
        tags: string[];
        description: string;
      }>
    )[0];
    const blob = JSON.stringify(rule.when_ast);
    expect(blob).toContain("sibling_prior_flag");
    expect(blob).toContain("has_etype");
    expect(rule.when_ast.type).toBe("and");
    expect(rule.tags).toContain("FLAG");
    expect(rule.description.toLowerCase()).toContain("sibling");
  });

  it("blank threshold still emits Observe JSON evaluate already runs", () => {
    const pack = emitVelocityPack({ field: "event_count_1h", op: "gte", value: 0 });
    expect(pack.mode).toBe("shadow");
    const rule = (pack.rules as Array<{ when: Array<{ field: string; value: number }> }>)[0];
    expect(rule.when[0].field).toBe("event_count_1h");
    expect(rule.when[0].value).toBe(0);
  });

  it("emits HAS_LIST from the shipped etype list", () => {
    const pack = emitHopPack({ etype: "HAS_LIST" });
    const rule = (pack.rules as Array<{ when_ast: { etype: string } }>)[0];
    expect(rule.when_ast.etype).toBe("HAS_LIST");
    expect(pack.mode).toBe("shadow");
  });
});
