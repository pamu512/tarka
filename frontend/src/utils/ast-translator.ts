/**
 * Semantic Operator Map — Rust / JSON AST condition operators → human-centric verbs.
 * Aligns with `ConditionOpName` in `frontend/src/types/jsonAst.ts`.
 */

/** Maps persisted AST operator names to analyst-facing verbs (present tense, lowercase phrase starters). */
export const AST_OPERATOR_VERBS: Readonly<Record<string, string>> = {
  gt: "exceeded",
  gte: "met or exceeded",
  lt: "fell below",
  lte: "was at or below",
  eq: "matches",
  not_eq: "does not match",
  in: "is one of",
  not_in: "is outside",
  contains: "includes known",
  starts_with: "starts with",
  ends_with: "ends with",
  regex: "matches pattern",
  is_true: "is true for",
  is_false: "is false for",
  exists: "has",
  not_exists: "does not have",
};

/** Feature / field keys → semantic labels for prose (not raw snake_case). */
export const FIELD_SEMANTIC_LABELS: Readonly<Record<string, string>> = {
  graph_score: "Network Risk Level",
  velocity_5m: "five-minute velocity",
  velocity_1h: "hourly velocity",
  velocity_24h: "24-hour velocity",
};

const OP_ALIASES: Readonly<Record<string, string>> = {
  ">": "gt",
  ">=": "gte",
  "<": "lt",
  "<=": "lte",
  "==": "eq",
  "!=": "not_eq",
  ne: "not_eq",
  IN: "in",
  "not in": "not_in",
};

function normalizeOp(op: string): string {
  const t = op.trim();
  const lower = t.toLowerCase();
  return OP_ALIASES[t] ?? OP_ALIASES[lower] ?? lower;
}

function humanizeFieldKey(field: string): string {
  return field
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/**
 * Turn a single AST-style condition into one readable sentence.
 *
 * @example translateOp('gt', 'velocity_1h', 5)
 *          → "exceeded the hourly limit of 5 transactions."
 */
export function translateOp(op: string, field: string, value: unknown): string {
  const fieldKey = field.trim();
  const nOp = normalizeOp(op);

  if (fieldKey === "velocity_1h" && nOp === "gt") {
    const n = typeof value === "number" ? value : Number(value);
    const limit = Number.isFinite(n) ? n : value;
    return `exceeded the hourly limit of ${limit} transactions.`;
  }

  const verb = AST_OPERATOR_VERBS[nOp] ?? normalizeOp(op);
  const label = FIELD_SEMANTIC_LABELS[fieldKey] ?? humanizeFieldKey(fieldKey);
  const formatted = formatScalar(value);

  switch (nOp) {
    case "contains":
      return `${verb} ${label}: ${formatted}.`;
    case "exists":
    case "not_exists":
      return `${verb} ${label}.`;
    case "is_true":
    case "is_false":
      return `${verb} ${label}.`;
    default:
      return `${verb} ${label} (${formatted}).`;
  }
}
