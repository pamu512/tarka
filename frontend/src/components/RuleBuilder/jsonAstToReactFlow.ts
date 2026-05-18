import type { Edge, Node } from "@xyflow/react";

import type { ConditionOpName, JsonAstNode } from "../../types/jsonAst";
import { isConditionOpName } from "../../types/jsonAst";
import type { FeatureKind } from "../../types/rules";
import { CompileToAstError, NODE_TYPES, normalizeOp, type RuleRootNodeData } from "./compileToAST";

const COL = 280;
const ROW = 100;

export type RuleRootMeta = {
  ruleId: string;
  tagsStr: string;
  scoreDeltaStr: string;
  description: string;
};

type OutletKind = "operator" | "graphRisk" | "logicAnd" | "logicOr";

type ExprBox = {
  nodes: Node[];
  edges: Edge[];
  maxX: number;
  minY: number;
  maxY: number;
  centerY: number;
  outletId: string;
  outletKind: OutletKind;
};

let idSeq = 0;
function nextId(prefix: string): string {
  idSeq += 1;
  return `${prefix}-${idSeq}`;
}

function eid(): string {
  return nextId("e");
}

function inferFeatureKind(value: unknown, op: string): FeatureKind {
  const n = normalizeOp(op);
  if (n === "exists" || n === "not_exists" || n === "is_true" || n === "is_false") {
    return "boolean";
  }
  if (typeof value === "number" && Number.isFinite(value)) return "number";
  if (typeof value === "boolean") return "boolean";
  if (Array.isArray(value)) return "string";
  return "string";
}

function formatValueStr(value: unknown, kind: FeatureKind, op: string): string {
  const n = normalizeOp(op);
  if (n === "in" || n === "not_in") {
    return JSON.stringify(value ?? []);
  }
  if (n === "exists" || n === "not_exists" || n === "is_true" || n === "is_false") {
    return "";
  }
  if (kind === "number" && typeof value === "number") return String(value);
  if (kind === "boolean") return value === true ? "true" : "false";
  if (value == null) return "";
  return String(value);
}

function coerceConditionOp(op: string): string {
  const n = normalizeOp(op);
  if (!isConditionOpName(n)) {
    throw new CompileToAstError(`Cannot map operator ${op} to JSON AST condition op`);
  }
  return n;
}

function edgeToLogicChild(
  sourceId: string,
  sourceKind: OutletKind,
  logicId: string,
  parentIsAnd: boolean,
): Edge {
  const sourceHandle =
    sourceKind === "operator" ? "o-out" : sourceKind === "graphRisk" ? "gr-out" : sourceKind === "logicAnd" ? "a-out" : "o-out";
  const targetHandle = parentIsAnd ? "a-in" : "o-in";
  return {
    id: eid(),
    source: sourceId,
    target: logicId,
    sourceHandle,
    targetHandle,
    animated: true,
  };
}

function edgeToRuleRoot(sourceId: string, sourceKind: OutletKind, rootId: string): Edge {
  const sourceHandle =
    sourceKind === "operator" ? "o-out" : sourceKind === "graphRisk" ? "gr-out" : sourceKind === "logicAnd" ? "a-out" : "o-out";
  return {
    id: eid(),
    source: sourceId,
    target: rootId,
    sourceHandle,
    targetHandle: "r-in",
    animated: true,
  };
}

function layoutExpr(ast: JsonAstNode, x: number, y: number): ExprBox {
  if (ast.type === "condition") {
    const opName = coerceConditionOp(ast.op);
    const kind = inferFeatureKind(ast.value, opName);
    const fid = nextId("feat");
    const oid = nextId("op");
    const nodes: Node[] = [
      {
        id: fid,
        type: NODE_TYPES.feature,
        position: { x, y },
        data: { field: ast.field, featureKind: kind },
      },
      {
        id: oid,
        type: NODE_TYPES.operator,
        position: { x: x + COL, y },
        data: { op: opName, valueStr: formatValueStr(ast.value, kind, opName) },
      },
    ];
    const edges: Edge[] = [
      {
        id: eid(),
        source: fid,
        target: oid,
        sourceHandle: "f-out",
        targetHandle: "f-in",
        animated: true,
      },
    ];
    const midY = y + 28;
    return {
      nodes,
      edges,
      maxX: x + COL * 2,
      minY: y,
      maxY: y + 72,
      centerY: midY,
      outletId: oid,
      outletKind: "operator",
    };
  }

  if (ast.type === "graph_condition") {
    const gid = nextId("gr");
    const nodes: Node[] = [
      {
        id: gid,
        type: NODE_TYPES.graphRisk,
        position: { x: x + 40, y },
        data: { thresholdStr: String(ast.threshold) },
      },
    ];
    const midY = y + 28;
    return {
      nodes,
      edges: [],
      maxX: x + COL + 120,
      minY: y,
      maxY: y + 72,
      centerY: midY,
      outletId: gid,
      outletKind: "graphRisk",
    };
  }

  const isAnd = ast.type === "and";
  if (ast.children.length === 0) {
    throw new CompileToAstError(`Empty ${ast.type} node`);
  }

  let curTop = y;
  const allNodes: Node[] = [];
  const allEdges: Edge[] = [];
  let maxSubX = x;
  const boxes: ExprBox[] = [];

  for (const child of ast.children) {
    const box = layoutExpr(child, x, curTop);
    allNodes.push(...box.nodes);
    allEdges.push(...box.edges);
    maxSubX = Math.max(maxSubX, box.maxX);
    boxes.push(box);
    curTop = box.maxY + ROW;
  }

  const minY = boxes[0].minY;
  const maxY = boxes[boxes.length - 1].maxY;
  const centerY = (minY + maxY) / 2;
  const logicId = nextId(isAnd ? "and" : "or");
  const logicX = maxSubX + 48;
  allNodes.push({
    id: logicId,
    type: isAnd ? NODE_TYPES.logicAnd : NODE_TYPES.logicOr,
    position: { x: logicX, y: centerY - 24 },
    data: {},
  });

  for (const b of boxes) {
    allEdges.push(edgeToLogicChild(b.outletId, b.outletKind, logicId, isAnd));
  }

  return {
    nodes: allNodes,
    edges: allEdges,
    maxX: logicX + 220,
    minY,
    maxY,
    centerY,
    outletId: logicId,
    outletKind: isAnd ? "logicAnd" : "logicOr",
  };
}

/**
 * Build React Flow nodes/edges from a persisted JSON AST (`when_ast`) + rule root metadata.
 */
export function jsonAstToReactFlow(ast: JsonAstNode, meta: RuleRootMeta): { nodes: Node[]; edges: Edge[] } {
  idSeq = 0;
  const expr = layoutExpr(ast, 0, 0);
  const rootId = nextId("root");
  const rootNode: Node = {
    id: rootId,
    type: NODE_TYPES.ruleRoot,
    position: { x: expr.maxX + 40, y: expr.centerY - 36 },
    data: {
      ruleId: meta.ruleId,
      tagsStr: meta.tagsStr,
      scoreDeltaStr: meta.scoreDeltaStr,
      description: meta.description,
    } satisfies RuleRootNodeData,
  };
  const nodes = [...expr.nodes, rootNode];
  const edges = [...expr.edges, edgeToRuleRoot(expr.outletId, expr.outletKind, rootId)];
  return { nodes, edges };
}

/** Convert legacy flat `when` rows to a JSON AST (AND). */
export function legacyWhenToJsonAst(when: Array<{ field: string; op: string; value?: unknown }>): JsonAstNode {
  if (!when.length) {
    throw new CompileToAstError("Rule has empty when[] — nothing to visualize.");
  }
  const leaves: JsonAstNode[] = when.map((w) => ({
    type: "condition",
    op: coerceConditionOp(w.op) as ConditionOpName,
    field: w.field,
    value: w.value,
  }));
  if (leaves.length === 1) return leaves[0];
  return { type: "and", children: leaves };
}

/** Hydrate canvas state from an API / pack rule record. */
export function packRuleRecordToFlow(rule: Record<string, unknown>): { nodes: Node[]; edges: Edge[] } {
  const meta: RuleRootMeta = {
    ruleId: String(rule.id ?? "rule"),
    tagsStr: Array.isArray(rule.tags) ? (rule.tags as string[]).join(", ") : "",
    scoreDeltaStr: String(rule.score_delta ?? "0"),
    description: typeof rule.description === "string" ? rule.description : "",
  };

  const rawAst = rule.when_ast;
  if (rawAst && typeof rawAst === "object" && rawAst !== null && "type" in rawAst) {
    return jsonAstToReactFlow(rawAst as JsonAstNode, meta);
  }

  const when = rule.when;
  if (Array.isArray(when) && when.length > 0) {
    const ast = legacyWhenToJsonAst(when as Array<{ field: string; op: string; value?: unknown }>);
    return jsonAstToReactFlow(ast, meta);
  }

  throw new CompileToAstError("This rule has no when_ast or non-empty when[] — open it in the YAML editor instead.");
}
