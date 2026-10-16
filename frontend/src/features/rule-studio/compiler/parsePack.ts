/**
 * parsePack: wire pack JSON → PackDraft.
 * No React imports. Unknown ops stay ConditionRows (never RawBlock).
 */
import { CODEC_V1 } from "../model/codecs";
import type { ConditionRow, PackDraft, RawBlock, RuleDraft } from "../model/uiPack";

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Deterministic id from prefix + index (draft-only; stripped on compile). */
function newId(prefix: string, salt = ""): string {
  const base = `${prefix}_${salt}`;
  let h = 2166136261;
  for (let i = 0; i < base.length; i++) {
    h ^= base.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return `${prefix}_${(h >>> 0).toString(16).slice(0, 8)}`;
}

/** Reserved: true when AST is flat leaf or one-level OR/AND of leaves. */
export function isShallowWhenAst(ast: unknown): boolean {
  if (!isRecord(ast)) return false;
  const t = ast.type;
  if (t === "leaf" || (typeof ast.op === "string" && typeof ast.field === "string")) {
    return true;
  }
  if (t === "or" || t === "and") {
    const kids = ast.children;
    if (!Array.isArray(kids) || kids.length === 0) return false;
    return kids.every(
      (c) =>
        isRecord(c) &&
        (c.type === "leaf" ||
          (typeof c.op === "string" && typeof c.field === "string")),
    );
  }
  return false;
}

function parseConditions(when: unknown, ruleId: string): ConditionRow[] {
  if (!Array.isArray(when)) return [];
  return when.map((c, i) => {
    const row = isRecord(c) ? c : {};
    const field = typeof row.field === "string" ? row.field : "";
    const op = typeof row.op === "string" ? row.op : "eq";
    return {
      id: newId("cond", `${ruleId}:${i}:${field}:${op}:${JSON.stringify(row.value)}`),
      field,
      op,
      value: row.value,
    };
  });
}

function parseRule(raw: unknown, index: number): RuleDraft {
  if (!isRecord(raw)) {
    return {
      id: newId("rule", String(index)),
      when: [],
      rawBlocks: [{ id: newId("raw", String(index)), kind: "unknown", json: raw }],
    };
  }

  const id =
    typeof raw.id === "string" && raw.id ? raw.id : newId("rule", String(index));
  const whenArr = Array.isArray(raw.when) ? raw.when : [];
  const hasWhen = whenArr.length > 0;
  const hasAst = raw.when_ast != null;

  if (hasWhen && hasAst) {
    return {
      id,
      when: [],
      rawBlocks: [{ id: newId("both", id), kind: "both_set_rule", json: raw }],
    };
  }

  // Any when_ast → RawBlock. Phase 1 form is flat-only; never silent-flatten.
  // isShallowWhenAst reserved for Phase 2 editable shallow OR.
  if (hasAst) {
    const draft: RuleDraft = {
      id,
      when: [],
      rawBlocks: [{ id: newId("ast", id), kind: "when_ast", json: raw.when_ast }],
    };
    if (typeof raw.score_delta === "number") draft.score_delta = raw.score_delta;
    if (Array.isArray(raw.tags)) draft.tags = raw.tags as string[];
    if (typeof raw.description === "string") draft.description = raw.description;
    return draft;
  }

  const draft: RuleDraft = {
    id,
    when: parseConditions(whenArr, id),
    rawBlocks: [],
  };
  if (typeof raw.score_delta === "number") draft.score_delta = raw.score_delta;
  if (Array.isArray(raw.tags)) draft.tags = raw.tags as string[];
  if (typeof raw.description === "string") draft.description = raw.description;
  return draft;
}

const KNOWN_PACK_KEYS = new Set([
  "version",
  "name",
  "mode",
  "description",
  "rules",
  "tag_rules",
  "canary_percent",
  "effective_at",
  "approved_by",
  "file",
]);

export function parsePack(json: unknown): PackDraft {
  if (!isRecord(json)) {
    return {
      codecVersion: CODEC_V1,
      rules: [],
      rawTopLevel: [{ id: newId("top"), kind: "unknown", json }],
    };
  }

  const draft: PackDraft = {
    codecVersion: CODEC_V1,
    rules: Array.isArray(json.rules)
      ? json.rules.map((r, i) => parseRule(r, i))
      : [],
    rawTopLevel: [],
  };

  if (typeof json.file === "string") draft.file = json.file;
  if (typeof json.name === "string") draft.name = json.name;
  if (typeof json.version === "number") draft.version = json.version;
  if (typeof json.mode === "string") draft.mode = json.mode;
  if (typeof json.description === "string") draft.description = json.description;
  if ("canary_percent" in json) {
    draft.canary_percent = json.canary_percent as number | null;
  }
  if ("effective_at" in json) {
    draft.effective_at = json.effective_at as string | null;
  }
  if ("approved_by" in json) {
    draft.approved_by = json.approved_by as string | null;
  }
  if ("tag_rules" in json) {
    draft.tag_rules = Array.isArray(json.tag_rules) ? json.tag_rules : [];
  }

  for (const [key, value] of Object.entries(json)) {
    if (KNOWN_PACK_KEYS.has(key)) continue;
    draft.rawTopLevel.push({
      id: newId("top", key),
      kind: "unknown",
      json: { key, value },
    });
  }

  return draft;
}
