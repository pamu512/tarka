import type { Edge, Node } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { compileToAST, compileVisualToDeployedJsonPack, isValidRuleConnection, NODE_TYPES } from "./compileToAST";

describe("compileToAST", () => {
  it("compiles AND chain to one rule with flat when", () => {
    const nodes: Node[] = [
      { id: "f1", type: NODE_TYPES.feature, position: { x: 0, y: 0 }, data: { field: "amount", featureKind: "number" } },
      { id: "o1", type: NODE_TYPES.operator, position: { x: 0, y: 0 }, data: { op: "gte", valueStr: "100" } },
      { id: "a1", type: NODE_TYPES.logicAnd, position: { x: 0, y: 0 }, data: {} },
      {
        id: "r1",
        type: NODE_TYPES.ruleRoot,
        position: { x: 0, y: 0 },
        data: { ruleId: "r1", tagsStr: "t1", scoreDeltaStr: "5", description: "" },
      },
    ];
    const edges: Edge[] = [
      { id: "e1", source: "f1", target: "o1", sourceHandle: "f-out", targetHandle: "f-in" },
      { id: "e2", source: "o1", target: "a1", sourceHandle: "o-out", targetHandle: "a-in" },
      { id: "e3", source: "a1", target: "r1", sourceHandle: "a-out", targetHandle: "r-in" },
    ];
    const pack = compileToAST(nodes, edges);
    expect(pack.rules).toHaveLength(1);
    const deployed = compileVisualToDeployedJsonPack(pack);
    expect(deployed.rules[0].when).toEqual([{ field: "amount", op: "gte", value: 100 }]);
  });

  it("rejects invalid connection feature→ruleRoot", () => {
    const nodes: Node[] = [
      { id: "f1", type: NODE_TYPES.feature, position: { x: 0, y: 0 }, data: { field: "x", featureKind: "string" } },
      { id: "r1", type: NODE_TYPES.ruleRoot, position: { x: 0, y: 0 }, data: { ruleId: "r", tagsStr: "", scoreDeltaStr: "0", description: "" } },
    ];
    const c = { source: "f1", target: "r1", sourceHandle: "f-out", targetHandle: "r-in" };
    expect(isValidRuleConnection(c, nodes)).toBe(false);
  });
});
