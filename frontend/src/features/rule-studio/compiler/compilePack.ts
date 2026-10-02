/**
 * compilePack: PackDraft → deterministic wire pack JSON.
 * Stable rule ids when missing; condition row ids are draft-only (stripped).
 */
import type { PackDraft, RuleDraft } from "../model/uiPack";

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Deterministic short hash of condition fingerprint (no Math.random). */
function shortHash(s: string): string {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16).slice(0, 8);
}

function slugify(s: string): string {
  const t = s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  return t || "rule";
}

export function stableRuleId(rule: RuleDraft): string {
  if (rule.id) return rule.id;
  const fingerprint = JSON.stringify(
    rule.when.map((c) => ({ field: c.field, op: c.op, value: c.value })),
  );
  return `studio_${slugify(rule.when[0]?.field ?? "pack")}_${shortHash(fingerprint)}`;
}

function compileRule(rule: RuleDraft): Record<string, unknown> {
  const both = rule.rawBlocks.find((b) => b.kind === "both_set_rule");
  if (both && isRecord(both.json)) {
    return { ...both.json };
  }

  const out: Record<string, unknown> = {
    id: stableRuleId(rule),
    when: rule.when.map((c) => {
      const cond: Record<string, unknown> = { field: c.field, op: c.op };
      if (c.value !== undefined) cond.value = c.value;
      return cond;
    }),
    tags: rule.tags ?? [],
    score_delta: rule.score_delta ?? 0,
    description: rule.description ?? "",
  };

  const astBlock = rule.rawBlocks.find((b) => b.kind === "when_ast");
  if (astBlock) {
    out.when_ast = astBlock.json;
  }

  for (const b of rule.rawBlocks) {
    if (b.kind === "unknown" && isRecord(b.json)) {
      Object.assign(out, b.json);
    }
  }

  return out;
}

export function compilePack(draft: PackDraft): unknown {
  const pack: Record<string, unknown> = {
    version: draft.version ?? 1,
    name: draft.name ?? "untitled",
    rules: draft.rules.map(compileRule),
  };

  if (draft.mode !== undefined) pack.mode = draft.mode;
  if (draft.description !== undefined) pack.description = draft.description;
  if (draft.tag_rules !== undefined) pack.tag_rules = draft.tag_rules;
  if ("canary_percent" in draft) pack.canary_percent = draft.canary_percent ?? null;
  if ("effective_at" in draft) pack.effective_at = draft.effective_at ?? null;
  if ("approved_by" in draft) pack.approved_by = draft.approved_by ?? null;
  if (draft.file !== undefined) pack.file = draft.file;

  for (const block of draft.rawTopLevel) {
    if (block.kind === "unknown" && isRecord(block.json) && typeof block.json.key === "string") {
      pack[block.json.key] = block.json.value;
    } else if (block.kind === "unknown" && isRecord(block.json)) {
      Object.assign(pack, block.json);
    }
  }

  return pack;
}
