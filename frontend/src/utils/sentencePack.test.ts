import { describe, expect, it } from "vitest";

import { emitHopPack, emitVelocityPack } from "./sentencePack";

describe("sentencePack", () => {
  it("emits Observe JSON for a velocity sentence using a canonical key", () => {
    const pack = emitVelocityPack({ field: "event_count_1h", op: "gte", value: 20 });
    expect(pack.mode).toBe("shadow");
    const rule = (pack.rules as Array<{ when: Array<{ field: string }> }>)[0];
    expect(rule.when[0].field).toBe("event_count_1h");
  });

  it("emits a signed hop etype only", () => {
    const pack = emitHopPack({ etype: "USES_DEVICE" });
    const rule = (pack.rules as Array<{ when_ast: { etype: string } }>)[0];
    expect(rule.when_ast.etype).toBe("USES_DEVICE");
    expect(pack.mode).toBe("shadow");
  });
});
