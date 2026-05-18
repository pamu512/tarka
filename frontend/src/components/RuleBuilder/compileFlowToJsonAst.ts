import { getIncomers, type Edge, type Node } from "@xyflow/react";

import {
  MAX_AST_CHILDREN,
  type ConditionOpName,
  type JsonAstNode,
  isConditionOpName,
} from "../../types/jsonAst";
import { graphRiskToJsonAstGraphCondition } from "./compiler";
import { CompileToAstError, NODE_TYPES, leafFromOperator, normalizeOp, ruleMetaFromRoot, type GraphRiskNodeData, type RuleRootNodeData } from "./compileToAST";

function coerceConditionOp(op: string): ConditionOpName {
  const n = normalizeOp(op);
  if (!isConditionOpName(n)) {
    throw new CompileToAstError(`Operator ${op} (normalized ${n}) is not allowed on the JSON AST path`);
  }
  return n;
}

function buildAstNode(n: Node, nodes: Node[], edges: Edge[], path: Set<string>): JsonAstNode {
  if (path.has(n.id)) {
    throw new CompileToAstError("Circular logic detected in the expression graph", n.id);
  }
  path.add(n.id);
  try {
    if (n.type === NODE_TYPES.operator) {
      const leaf = leafFromOperator(n, nodes, edges);
      const field = leaf.field.trim();
      if (!field) {
        throw new CompileToAstError("Condition field is required", n.id);
      }
      return {
        type: "condition",
        op: coerceConditionOp(leaf.op),
        field,
        value: leaf.value,
      };
    }
    if (n.type === NODE_TYPES.graphRisk) {
      try {
        return graphRiskToJsonAstGraphCondition(n.id, n.data as GraphRiskNodeData);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        throw new CompileToAstError(msg, n.id);
      }
    }
    if (n.type === NODE_TYPES.logicAnd || n.type === NODE_TYPES.logicOr) {
      const incomers = getIncomers(n, nodes, edges);
      if (incomers.length === 0) {
        throw new CompileToAstError(`${n.type === NODE_TYPES.logicAnd ? "AND" : "OR"} node has no inputs (add child nodes)`, n.id);
      }
      if (incomers.length > MAX_AST_CHILDREN) {
        throw new CompileToAstError(`Too many inputs (${incomers.length}; max ${MAX_AST_CHILDREN})`, n.id);
      }
      const children = incomers.map((c) => buildAstNode(c, nodes, edges, path));
      return n.type === NODE_TYPES.logicAnd ? { type: "and", children } : { type: "or", children };
    }
    throw new CompileToAstError(`Invalid node type in expression tree: ${String(n.type)}`, n.id);
  } finally {
    path.delete(n.id);
  }
}

/**
 * Build a single-root JSON AST from the canvas topology (Feature → Operator → AND/OR → Rule root).
 * Matches ``JsonAstNode`` / Pydantic discriminated models on the decision-api.
 */
export function compileFlowToJsonAst(nodes: Node[], edges: Edge[]): JsonAstNode {
  const roots = nodes.filter((n) => n.type === NODE_TYPES.ruleRoot);
  if (roots.length !== 1) {
    throw new CompileToAstError("Exactly one Rule root node is required on the canvas.");
  }
  const rr = roots[0];
  const incomers = getIncomers(rr, nodes, edges);
  if (incomers.length !== 1) {
    throw new CompileToAstError("Rule root must have exactly one incoming edge from AND, OR, Operator, or Graph risk.");
  }
  const top = incomers[0];
  return buildAstNode(top, nodes, edges, new Set());
}

export function readRuleRootMeta(nodes: Node[]): {
  ruleId: string;
  tags: string[];
  scoreDelta: number;
  description: string;
} {
  const roots = nodes.filter((n) => n.type === NODE_TYPES.ruleRoot);
  if (roots.length !== 1) {
    throw new CompileToAstError("Exactly one Rule root node is required on the canvas.");
  }
  const m = ruleMetaFromRoot(roots[0]);
  return {
    ruleId: m.baseId,
    tags: m.tags,
    scoreDelta: m.score_delta,
    description: m.description,
  };
}

/** Suggested pack name from rule root description / id (caller may override). */
export function defaultPackNameFromCanvas(nodes: Node[]): string {
  const roots = nodes.filter((n) => n.type === NODE_TYPES.ruleRoot);
  if (roots.length !== 1) return "visual_ast_pack";
  const d = roots[0].data as RuleRootNodeData;
  const id = (d.ruleId || "").trim();
  if (id) return `pack_${id}`;
  return "visual_ast_pack";
}
