/**
 * Visual Rule Builder compiler — Graph Risk node ↔ Rust ``GraphMatch`` / JSON AST ``graph_condition``.
 *
 * Deployed ``when`` leaves use ``{ op: "gt", field: "graph_score", value }`` (see ``tarka-core`` evaluator).
 * Structured AST export uses ``{ type: "graph_condition", operator: "gt", threshold }``.
 */

import type { JsonAstGraphCondition } from "../../types/jsonAst";
import type { VisualAstLeaf } from "../../types/rules";

/** React Flow node ``type`` string for the Graph Risk palette node. */
export const GRAPH_RISK_NODE_TYPE = "graphRisk" as const;

export type GraphRiskNodeData = {
  /** Threshold for ``context.graph_score`` strictly greater than this value (same semantics as Rust). */
  thresholdStr: string;
};

export class GraphRiskCompileError extends Error {
  constructor(
    message: string,
    public readonly nodeId?: string,
  ) {
    super(message);
    this.name = "GraphRiskCompileError";
  }
}

function parseThreshold(data: GraphRiskNodeData, nodeId?: string): number {
  const t = Number((data.thresholdStr ?? "").trim());
  if (!Number.isFinite(t)) {
    throw new GraphRiskCompileError("Graph risk: threshold must be a finite number", nodeId);
  }
  return t;
}

/** Flat ``when`` leaf consumed by ``compileVisualToDeployedJsonPack`` / Rust pack parsers. */
export function graphRiskToVisualAstLeaf(nodeId: string, data: GraphRiskNodeData): VisualAstLeaf {
  const threshold = parseThreshold(data, nodeId);
  return { op: "gt", field: "graph_score", value: threshold };
}

/** JSON AST node for ``when_ast`` saves / discriminated union beside ``condition`` / ``and`` / ``or``. */
export function graphRiskToJsonAstGraphCondition(nodeId: string, data: GraphRiskNodeData): JsonAstGraphCondition {
  const threshold = parseThreshold(data, nodeId);
  return { type: "graph_condition", operator: "gt", threshold };
}
