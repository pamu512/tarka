import type { Edge, Node } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { emitHopPack } from "../../utils/sentencePack";
import { compileHopEtypeFromCanvas } from "./compileHopEtype";
import { validateCanvasForAstSave } from "./validateRuleBuilderCanvas";

const hopRoot: Node = {
  id: "r1",
  type: "ruleRoot",
  position: { x: 0, y: 0 },
  data: { ruleId: "h", tagsStr: "", scoreDeltaStr: "18", description: "" },
};

const hopToRoot: Edge[] = [{ id: "e", source: "h1", target: "r1", sourceHandle: "he-out", targetHandle: "r-in" }];

function hopCanvas(etype: string): Node[] {
  return [
    { id: "h1", type: "hopEtype", position: { x: 0, y: 0 }, data: { etype } },
    hopRoot,
  ];
}

describe("compileHopEtypeFromCanvas", () => {
  it("compiles HAS_LIST to the same when_ast as emitHopPack", () => {
    const nodes = hopCanvas("HAS_LIST");
    const got = compileHopEtypeFromCanvas(nodes as never, hopToRoot as never);
    const pack = emitHopPack({ etype: "HAS_LIST" });
    const rule = (pack.rules as Array<{ when_ast: unknown; tags: string[] }>)[0];
    expect(got.ok).toBe(true);
    if (!got.ok) return;
    expect(got.when_ast).toEqual(rule.when_ast);
    expect(got.tags).toEqual(rule.tags);
  });

  it("returns ok false when etype is not a catalog hop", () => {
    const got = compileHopEtypeFromCanvas(hopCanvas("NOPE") as never, hopToRoot as never);
    expect(got.ok).toBe(false);
  });

  it("validateCanvasForAstSave succeeds when hop compile is ok", () => {
    expect(validateCanvasForAstSave(hopCanvas("HAS_LIST"), hopToRoot)).toEqual({ ok: true });
  });
});
