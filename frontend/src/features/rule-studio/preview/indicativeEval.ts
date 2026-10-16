/**
 * Indicative client-side evaluator (subset of ops). Not Rust / server truth.
 * Label UI: "Indicative (not Rust)".
 */
import type { PackDraft } from "../model/uiPack";
import { compilePack } from "../compiler/compilePack";

export type IndicativeResult = { hits: string[]; score: number };

function getField(payload: Record<string, unknown>, field: string): unknown {
  return payload[field];
}

function matchCond(
  payload: Record<string, unknown>,
  field: string,
  op: string,
  value: unknown,
): boolean {
  const actual = getField(payload, field);
  switch (op) {
    case "eq":
      return actual === value;
    case "not_eq":
      return actual !== value;
    case "gt":
      return typeof actual === "number" && typeof value === "number" && actual > value;
    case "gte":
      return typeof actual === "number" && typeof value === "number" && actual >= value;
    case "lt":
      return typeof actual === "number" && typeof value === "number" && actual < value;
    case "lte":
      return typeof actual === "number" && typeof value === "number" && actual <= value;
    case "contains":
      return typeof actual === "string" && typeof value === "string" && actual.includes(value);
    case "is_true":
      return actual === true;
    case "is_false":
      return actual === false;
    case "in":
      return Array.isArray(value) && value.includes(actual);
    case "starts_with":
      return typeof actual === "string" && typeof value === "string" && actual.startsWith(value);
    case "ends_with":
      return typeof actual === "string" && typeof value === "string" && actual.endsWith(value);
    case "exists":
      return actual !== undefined && actual !== null;
    case "not_exists":
      return actual === undefined || actual === null;
    default:
      return false;
  }
}

export function indicativeEval(
  packOrDraft: unknown | PackDraft,
  payload: Record<string, unknown>,
): IndicativeResult {
  const pack =
    packOrDraft &&
    typeof packOrDraft === "object" &&
    "codecVersion" in (packOrDraft as object)
      ? (compilePack(packOrDraft as PackDraft) as Record<string, unknown>)
      : (packOrDraft as Record<string, unknown>);

  const rules = Array.isArray(pack.rules) ? pack.rules : [];
  const hits: string[] = [];
  let score = 0;

  for (const raw of rules) {
    if (!raw || typeof raw !== "object") continue;
    const rule = raw as Record<string, unknown>;
    const id = typeof rule.id === "string" ? rule.id : "?";
    if (rule.when_ast != null && Array.isArray(rule.when) && (rule.when as unknown[]).length > 0) {
      continue; // both-set never fires
    }
    if (rule.when_ast != null) continue; // AST not evaluated client-side
    const when = Array.isArray(rule.when) ? rule.when : [];
    if (when.length === 0) continue;
    const ok = when.every((c) => {
      if (!c || typeof c !== "object") return false;
      const cond = c as Record<string, unknown>;
      return matchCond(
        payload,
        String(cond.field ?? ""),
        String(cond.op ?? ""),
        cond.value,
      );
    });
    if (ok) {
      hits.push(id);
      score += typeof rule.score_delta === "number" ? rule.score_delta : 0;
    }
  }

  return { hits, score };
}
