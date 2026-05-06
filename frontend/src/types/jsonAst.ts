/**
 * JSON rule AST — mirrors `decision_api.ast_models` (discriminated union, same caps).
 * @see services/decision-api/src/decision_api/ast_models.py
 */

export const MAX_AST_DEPTH = 24;
export const MAX_AST_NODES = 384;
export const MAX_AST_CHILDREN = 32;
export const MAX_AST_FIELD_LEN = 128;
export const MAX_AST_VALUE_LEN = 1024;

/** Must match ``ConditionOpName`` in Python exactly. */
export const CONDITION_OPS = [
  "eq",
  "not_eq",
  "gte",
  "gt",
  "lte",
  "lt",
  "in",
  "not_in",
  "contains",
  "starts_with",
  "ends_with",
  "regex",
  "is_true",
  "is_false",
  "exists",
  "not_exists",
] as const;

export type ConditionOpName = (typeof CONDITION_OPS)[number];

export type JsonAstCondition = {
  type: "condition";
  op: ConditionOpName;
  field: string;
  value?: unknown;
};

export type JsonAstAnd = {
  type: "and";
  children: JsonAstNode[];
};

export type JsonAstOr = {
  type: "or";
  children: JsonAstNode[];
};

export type JsonAstNode = JsonAstCondition | JsonAstAnd | JsonAstOr;

export function isConditionOpName(s: string): s is ConditionOpName {
  return (CONDITION_OPS as readonly string[]).includes(s);
}

export function astDepth(node: JsonAstNode): number {
  if (node.type === "condition") return 1;
  return 1 + Math.max(0, ...node.children.map(astDepth));
}

export function astNodeCount(node: JsonAstNode): number {
  if (node.type === "condition") return 1;
  return 1 + node.children.reduce((a, c) => a + astNodeCount(c), 0);
}
