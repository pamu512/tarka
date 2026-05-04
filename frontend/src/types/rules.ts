/**
 * Visual rule JSON AST v1 — mirrors `decision_api.rule_compiler_api` / Rust `when` compile path.
 * @see services/decision-api/src/decision_api/rule_compiler_api.py
 */

/** Leaf condition: evaluated against the feature map (flattened payload + metadata). */
export type VisualAstLeaf = {
  op: string;
  field: string;
  value?: unknown;
};

/** One authored rule (may compile to multiple flat rules when OR groups are present). */
export type VisualAstRule = {
  id: string;
  all_of: VisualAstLeaf[];
  any_of: VisualAstLeaf[];
  tags: string[];
  score_delta: number;
  description: string;
};

/** Pack envelope POSTed to `/v1/rules/visual/compile` and `/v1/rules/visual/evaluate-dry-run`. */
export type VisualAstPack = {
  name: string;
  rules: VisualAstRule[];
  tag_rules: unknown[];
};

/** Compiled deployable rule (Rust `parse_active_packs` / `when` array). */
export type CompiledRuleWhenCondition = {
  field: string;
  op: string;
  value?: unknown;
};

export type CompiledRule = {
  id: string;
  when: CompiledRuleWhenCondition[];
  tags: string[];
  score_delta: number;
  description?: string;
};

export type CompiledRulePack = {
  name: string;
  rules: CompiledRule[];
  tag_rules: unknown[];
  compiled_from?: string;
};

/** Operators supported per feature kind (subset aligned with Rust `match_condition`). */
export const NUMERIC_OPS = ["eq", "not_eq", "gt", "gte", "lt", "lte", "in", "not_in"] as const;
export const STRING_OPS = [
  "eq",
  "not_eq",
  "contains",
  "starts_with",
  "ends_with",
  "regex",
  "in",
  "not_in",
] as const;
export const BOOLEAN_OPS = ["eq", "not_eq", "is_true", "is_false"] as const;

export type FeatureKind = "number" | "string" | "boolean";
