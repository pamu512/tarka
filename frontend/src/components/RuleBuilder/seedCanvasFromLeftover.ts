import type { Edge, Node } from "@xyflow/react";

import type { AuthorCatalog } from "../../domain/authorCatalog";
import { parseHopEtype, parseVelocityField } from "../../utils/leftoverVisualQuery";
import { NODE_TYPES, type FeatureNodeData, type OperatorNodeData, type RuleRootNodeData } from "./compileToAST";

function leftoverRoot(ruleId: string): Node {
  return {
    id: "root-1",
    type: NODE_TYPES.ruleRoot,
    position: { x: 720, y: 24 },
    data: {
      ruleId,
      tagsStr: "",
      scoreDeltaStr: "0",
      description: "",
    } satisfies RuleRootNodeData,
  };
}

export function seedCanvasFromLeftover(
  catalog: AuthorCatalog,
  q: URLSearchParams,
): { nodes: Node[]; edges: Edge[] } | null {
  if (q.get("from") !== "leftover") return null;

  const etype = parseHopEtype(catalog, q.get("etype"));
  if (etype) {
    return {
      nodes: [
        {
          id: "hop-1",
          type: NODE_TYPES.hopEtype,
          position: { x: 260, y: 32 },
          data: { etype },
        },
        leftoverRoot(`leftover_${etype.toLowerCase()}`),
      ],
      edges: [{ id: "e-he-r", source: "hop-1", target: "root-1", sourceHandle: "he-out", targetHandle: "r-in" }],
    };
  }

  const field = parseVelocityField(catalog, q.get("field"));
  if (field) {
    return {
      nodes: [
        {
          id: "feat-1",
          type: NODE_TYPES.feature,
          position: { x: 0, y: 40 },
          data: { field, featureKind: "number" } satisfies FeatureNodeData,
        },
        {
          id: "op-1",
          type: NODE_TYPES.operator,
          position: { x: 260, y: 32 },
          data: { op: "gte", valueStr: "0" } satisfies OperatorNodeData,
        },
        leftoverRoot("leftover_observe"),
      ],
      edges: [
        { id: "e-f-op", source: "feat-1", target: "op-1", sourceHandle: "f-out", targetHandle: "f-in" },
        { id: "e-op-r", source: "op-1", target: "root-1", sourceHandle: "o-out", targetHandle: "r-in" },
      ],
    };
  }

  return null;
}
