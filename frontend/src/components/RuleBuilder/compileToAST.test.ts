import type { Edge, Node } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { compileFlowToJsonAst } from "./compileFlowToJsonAst";
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

  it("exports JSON AST with graph_condition when Graph risk is wired into AND", () => {
    const nodes: Node[] = [
      { id: "gr1", type: NODE_TYPES.graphRisk, position: { x: 0, y: 0 }, data: { thresholdStr: "0.75" } },
      { id: "a1", type: NODE_TYPES.logicAnd, position: { x: 0, y: 0 }, data: {} },
      {
        id: "r1",
        type: NODE_TYPES.ruleRoot,
        position: { x: 0, y: 0 },
        data: { ruleId: "graph_gate", tagsStr: "", scoreDeltaStr: "1", description: "graph" },
      },
    ];
    const edges: Edge[] = [
      { id: "e1", source: "gr1", target: "a1", sourceHandle: "gr-out", targetHandle: "a-in" },
      { id: "e2", source: "a1", target: "r1", sourceHandle: "a-out", targetHandle: "r-in" },
    ];
    const ast = compileFlowToJsonAst(nodes, edges);
    expect(ast).toEqual({
      type: "and",
      children: [{ type: "graph_condition", operator: "gt", threshold: 0.75 }],
    });
  });

  it("exports deployed when with graph_score operator for Graph risk (Rust GraphMatch wire shape)", () => {
    const nodes: Node[] = [
      { id: "gr1", type: NODE_TYPES.graphRisk, position: { x: 0, y: 0 }, data: { thresholdStr: "0.6" } },
      { id: "r1", type: NODE_TYPES.ruleRoot, position: { x: 0, y: 0 }, data: { ruleId: "g", tagsStr: "", scoreDeltaStr: "0", description: "" } },
    ];
    const edges: Edge[] = [{ id: "e1", source: "gr1", target: "r1", sourceHandle: "gr-out", targetHandle: "r-in" }];
    const pack = compileToAST(nodes, edges);
    const deployed = compileVisualToDeployedJsonPack(pack);
    expect(deployed.rules[0].when).toEqual([{ field: "graph_score", op: "gt", value: 0.6 }]);
  });

  it("rejects invalid connection feature→ruleRoot", () => {
    const nodes: Node[] = [
      { id: "f1", type: NODE_TYPES.feature, position: { x: 0, y: 0 }, data: { field: "x", featureKind: "string" } },
      { id: "r1", type: NODE_TYPES.ruleRoot, position: { x: 0, y: 0 }, data: { ruleId: "r", tagsStr: "", scoreDeltaStr: "0", description: "" } },
    ];
    const c = { source: "f1", target: "r1", sourceHandle: "f-out", targetHandle: "r-in" };
    expect(isValidRuleConnection(c, nodes)).toBe(false);
  });

  it("allows hopEtype he-out to the same targets as Graph risk", () => {
    const hop: Node = { id: "h1", type: "hopEtype", position: { x: 0, y: 0 }, data: { etype: "HAS_LIST" } };
    const and: Node = { id: "a1", type: NODE_TYPES.logicAnd, position: { x: 0, y: 0 }, data: {} };
    const or: Node = { id: "o1", type: NODE_TYPES.logicOr, position: { x: 0, y: 0 }, data: {} };
    const root: Node = {
      id: "r1",
      type: NODE_TYPES.ruleRoot,
      position: { x: 0, y: 0 },
      data: { ruleId: "h", tagsStr: "", scoreDeltaStr: "18", description: "" },
    };
    expect(isValidRuleConnection({ source: "h1", target: "r1", sourceHandle: "he-out", targetHandle: "r-in" }, [hop, root])).toBe(
      true,
    );
    expect(isValidRuleConnection({ source: "h1", target: "a1", sourceHandle: "he-out", targetHandle: "a-in" }, [hop, and])).toBe(
      true,
    );
    expect(isValidRuleConnection({ source: "h1", target: "o1", sourceHandle: "he-out", targetHandle: "o-in" }, [hop, or])).toBe(
      true,
    );
    expect(isValidRuleConnection({ source: "h1", target: "r1", sourceHandle: "gr-out", targetHandle: "r-in" }, [hop, root])).toBe(
      false,
    );
  });
});
