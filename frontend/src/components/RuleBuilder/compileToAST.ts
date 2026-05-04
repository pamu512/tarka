import { getIncomers, type Connection, type Edge, type Node } from "@xyflow/react";

import type { CompiledRulePack, FeatureKind, VisualAstLeaf, VisualAstPack, VisualAstRule } from "../../types/rules";
import { BOOLEAN_OPS, NUMERIC_OPS, STRING_OPS } from "../../types/rules";

export const NODE_TYPES = {
  feature: "feature",
  operator: "operator",
  logicAnd: "logicAnd",
  logicOr: "logicOr",
  ruleRoot: "ruleRoot",
} as const;

export type FeatureNodeData = {
  field: string;
  featureKind: FeatureKind;
};

export type OperatorNodeData = {
  op: string;
  /** Raw string from UI; parsed by `parseOperatorValue`. */
  valueStr: string;
};

export type RuleRootNodeData = {
  ruleId: string;
  tagsStr: string;
  scoreDeltaStr: string;
  description: string;
};

export class CompileToAstError extends Error {
  constructor(
    message: string,
    public readonly nodeId?: string,
  ) {
    super(message);
    this.name = "CompileToAstError";
  }
}

const ALL_OPS = new Set<string>([
  ...NUMERIC_OPS,
  ...STRING_OPS,
  ...BOOLEAN_OPS,
  "exists",
  "not_exists",
]);

/** Map friendly UI ops to Rust/json_rules op names. */
export function normalizeOp(op: string): string {
  const o = (op || "").trim();
  const table: Record<string, string> = {
    "==": "eq",
    "!=": "not_eq",
    ne: "not_eq",
    ">": "gt",
    "<": "lt",
    ">=": "gte",
    "<=": "lte",
    IN: "in",
    "NOT IN": "not_in",
    "not in": "not_in",
  };
  return table[o] ?? o.toLowerCase();
}

export function parseOperatorValue(kind: FeatureKind, op: string, valueStr: string): unknown {
  const n = normalizeOp(op);
  if (n === "exists" || n === "not_exists" || n === "is_true" || n === "is_false") {
    return null;
  }
  if (n === "in" || n === "not_in") {
    const raw = valueStr.trim();
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      throw new CompileToAstError("IN / NOT IN requires a JSON array, e.g. [\"US\",\"CA\"]");
    }
    return parsed;
  }
  if (kind === "number") {
    const v = Number(valueStr.trim());
    if (Number.isNaN(v)) {
      throw new CompileToAstError(`Expected a number for value, got: ${valueStr}`);
    }
    return v;
  }
  if (kind === "boolean") {
    const s = valueStr.trim().toLowerCase();
    if (s === "true") return true;
    if (s === "false") return false;
    throw new CompileToAstError(`Expected true/false, got: ${valueStr}`);
  }
  return valueStr;
}

export function allowedOpsForKind(kind: FeatureKind): readonly string[] {
  if (kind === "number") return NUMERIC_OPS;
  if (kind === "string") return STRING_OPS;
  return BOOLEAN_OPS;
}

export function validateOpForKind(kind: FeatureKind, op: string): void {
  const n = normalizeOp(op);
  if (!ALL_OPS.has(n)) {
    throw new CompileToAstError(`Unsupported operator: ${op} (normalized: ${n})`);
  }
  const allowed = allowedOpsForKind(kind);
  if (!allowed.includes(n as (typeof allowed)[number])) {
    throw new CompileToAstError(`Operator ${n} is not valid for ${kind} features (allowed: ${allowed.join(", ")})`);
  }
}

function leafFromOperator(opNode: Node, nodes: Node[], edges: Edge[]): VisualAstLeaf {
  if (opNode.type !== NODE_TYPES.operator) {
    throw new CompileToAstError("Internal: leafFromOperator on non-operator", opNode.id);
  }
  const incomers = getIncomers(opNode, nodes, edges);
  const feat = incomers.find((n) => n.type === NODE_TYPES.feature);
  if (!feat) {
    throw new CompileToAstError("Each Operator node must be connected from exactly one Feature node", opNode.id);
  }
  if (incomers.length !== 1) {
    throw new CompileToAstError("Operator must have exactly one incoming Feature connection", opNode.id);
  }
  const fd = feat.data as FeatureNodeData;
  const od = opNode.data as OperatorNodeData;
  validateOpForKind(fd.featureKind, od.op);
  const value = parseOperatorValue(fd.featureKind, od.op, od.valueStr);
  return { field: fd.field.trim(), op: normalizeOp(od.op), value };
}

/** Collect leaf conditions under an AND node (flatten nested AND). */
function flattenAnd(andId: string, nodes: Node[], edges: Edge[]): VisualAstLeaf[] {
  const node = nodes.find((n) => n.id === andId);
  if (!node || node.type !== NODE_TYPES.logicAnd) {
    throw new CompileToAstError("Expected logic AND node", andId);
  }
  const leaves: VisualAstLeaf[] = [];
  const incomers = getIncomers(node, nodes, edges);
  if (incomers.length === 0) {
    throw new CompileToAstError("AND node has no inputs", andId);
  }
  for (const inc of incomers) {
    if (inc.type === NODE_TYPES.operator) {
      leaves.push(leafFromOperator(inc, nodes, edges));
    } else if (inc.type === NODE_TYPES.logicAnd) {
      leaves.push(...flattenAnd(inc.id, nodes, edges));
    } else if (inc.type === NODE_TYPES.logicOr) {
      throw new CompileToAstError(
        "Nested OR under AND is not supported for JSON export — pull OR above the AND or use the Rego compile route.",
        inc.id,
      );
    } else {
      throw new CompileToAstError(`Invalid input to AND (${inc.type})`, inc.id);
    }
  }
  return leaves;
}

function ruleMetaFromRoot(rr: Node): Pick<VisualAstRule, "tags" | "score_delta" | "description"> & { baseId: string } {
  const d = rr.data as RuleRootNodeData;
  const tags = d.tagsStr
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  const score = Number(d.scoreDeltaStr.trim());
  if (Number.isNaN(score)) {
    throw new CompileToAstError("Rule root: score delta must be a number", rr.id);
  }
  const baseId = (d.ruleId || "").trim();
  if (!baseId) {
    throw new CompileToAstError("Rule root: id is required", rr.id);
  }
  return {
    baseId,
    tags,
    score_delta: score,
    description: (d.description || "").trim(),
  };
}

/**
 * Traverse the React Flow graph and produce a `VisualAstPack` accepted by
 * `POST /v1/rules/visual/compile` (flat `all_of` leaves per rule; OR branches become multiple rules).
 */
export function compileToAST(nodes: Node[], edges: Edge[]): VisualAstPack {
  const roots = nodes.filter((n) => n.type === NODE_TYPES.ruleRoot);
  if (roots.length !== 1) {
    throw new CompileToAstError("Exactly one Rule root node is required on the canvas.");
  }
  const rr = roots[0];
  const incomers = getIncomers(rr, nodes, edges);
  if (incomers.length !== 1) {
    throw new CompileToAstError("Rule root must have exactly one incoming edge from AND, OR, or Operator.");
  }
  const top = incomers[0];
  const meta = ruleMetaFromRoot(rr);
  const rules: VisualAstRule[] = [];

  if (top.type === NODE_TYPES.operator) {
    rules.push({
      id: meta.baseId,
      all_of: [leafFromOperator(top, nodes, edges)],
      any_of: [],
      tags: meta.tags,
      score_delta: meta.score_delta,
      description: meta.description,
    });
  } else if (top.type === NODE_TYPES.logicAnd) {
    rules.push({
      id: meta.baseId,
      all_of: flattenAnd(top.id, nodes, edges),
      any_of: [],
      tags: meta.tags,
      score_delta: meta.score_delta,
      description: meta.description,
    });
  } else if (top.type === NODE_TYPES.logicOr) {
    const branches = getIncomers(top, nodes, edges);
    if (branches.length < 2) {
      throw new CompileToAstError("OR node must have at least two incoming branches.");
    }
    branches.forEach((br, i) => {
      let leaves: VisualAstLeaf[];
      if (br.type === NODE_TYPES.operator) {
        leaves = [leafFromOperator(br, nodes, edges)];
      } else if (br.type === NODE_TYPES.logicAnd) {
        leaves = flattenAnd(br.id, nodes, edges);
      } else {
        throw new CompileToAstError(`OR branch must be Operator or AND, got ${br.type}`, br.id);
      }
      rules.push({
        id: `${meta.baseId}__or_${i}`,
        all_of: leaves,
        any_of: [],
        tags: meta.tags,
        score_delta: meta.score_delta,
        description: meta.description,
      });
    });
  } else {
    throw new CompileToAstError(`Rule root cannot connect from ${top.type}`, top.id);
  }

  return {
    name: "visual_canvas_pack",
    rules,
    tag_rules: [],
  };
}

/** Same shape as decision-api `_compile_to_json_rules` output (Rust `when` list). */
export function compileVisualToDeployedJsonPack(pack: VisualAstPack): CompiledRulePack {
  const rules = pack.rules.map((r) => ({
    id: r.id,
    when: [...r.all_of, ...r.any_of].map((l) => ({
      field: l.field,
      op: normalizeOp(l.op),
      value: l.value,
    })),
    tags: r.tags,
    score_delta: r.score_delta,
    description: r.description,
  }));
  return {
    name: pack.name,
    rules,
    tag_rules: pack.tag_rules,
    compiled_from: "visual_ast_v1",
  };
}

export function isValidRuleConnection(conn: Connection, nodes: Node[]): boolean {
  const s = nodes.find((n) => n.id === conn.source);
  const t = nodes.find((n) => n.id === conn.target);
  if (!s || !t) return false;

  if (s.type === NODE_TYPES.feature && t.type === NODE_TYPES.operator) {
    return conn.sourceHandle === "f-out" && conn.targetHandle === "f-in";
  }
  if (s.type === NODE_TYPES.operator) {
    if (conn.sourceHandle !== "o-out") return false;
    if (t.type === NODE_TYPES.logicAnd) return conn.targetHandle === "a-in";
    if (t.type === NODE_TYPES.logicOr) return conn.targetHandle === "o-in";
    if (t.type === NODE_TYPES.ruleRoot) return conn.targetHandle === "r-in";
    return false;
  }
  if (s.type === NODE_TYPES.logicAnd && conn.sourceHandle === "a-out") {
    if (t.type === NODE_TYPES.logicAnd && conn.targetHandle === "a-in") return true;
    if (t.type === NODE_TYPES.logicOr && conn.targetHandle === "o-in") return true;
    if (t.type === NODE_TYPES.ruleRoot && conn.targetHandle === "r-in") return true;
    return false;
  }
  if (s.type === NODE_TYPES.logicOr && conn.sourceHandle === "o-out") {
    if (t.type === NODE_TYPES.logicAnd && conn.targetHandle === "a-in") return true;
    if (t.type === NODE_TYPES.logicOr && conn.targetHandle === "o-in") return true;
    if (t.type === NODE_TYPES.ruleRoot && conn.targetHandle === "r-in") return true;
    return false;
  }
  return false;
}
