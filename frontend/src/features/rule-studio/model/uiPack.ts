import { CODEC_V1, type CodecVersion } from "./codecs";

/** 9 ops the manual Rules form ships with typed widgets. */
export const WIDGET_OPS = [
  "eq",
  "gt",
  "gte",
  "lt",
  "lte",
  "in",
  "contains",
  "is_true",
  "is_false",
] as const;

export type WidgetOp = (typeof WIDGET_OPS)[number];

/**
 * Full evaluator set (16) from json_rules.py.
 * Ops outside WIDGET_OPS (and any unknown) stay editable generic rows — never RawBlock.
 */
export const EVALUATOR_OPS: readonly string[] = [
  "eq",
  "not_eq",
  "gt",
  "gte",
  "lt",
  "lte",
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
];

export interface ConditionRow {
  id: string;
  field: string;
  op: string;
  value: unknown;
}

export interface RawBlock {
  id: string;
  kind: "when_ast" | "both_set_rule" | "unknown";
  json: unknown;
}

export interface RuleDraft {
  id: string;
  when: ConditionRow[];
  score_delta?: number;
  tags?: string[];
  rawBlocks: RawBlock[];
}

export interface PackDraft {
  codecVersion: CodecVersion;
  file?: string;
  mode?: string;
  rules: RuleDraft[];
  tag_rules?: unknown[];
  rawTopLevel: RawBlock[];
}

export function emptyPackDraft(): PackDraft {
  return {
    codecVersion: CODEC_V1,
    rules: [],
    rawTopLevel: [],
  };
}

export function isWidgetOp(op: string): op is WidgetOp {
  return (WIDGET_OPS as readonly string[]).includes(op);
}
