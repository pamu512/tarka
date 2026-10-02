import { create } from "zustand";
import { compilePack } from "../compiler/compilePack";
import { parsePack } from "../compiler/parsePack";
import { emptyPackDraft, type ConditionRow, type PackDraft } from "../model/uiPack";

type PackDraftState = {
  draft: PackDraft;
  dirty: boolean;
  jsonText: string;
  loadFromJson: (json: unknown) => void;
  /** Post-save: replace draft from server-normalized pack; clears dirty. */
  hydrateFromServerPack: (pack: unknown) => void;
  setCondition: (ruleId: string, conditionId: string, patch: Partial<ConditionRow>) => void;
  addCondition: (ruleId: string, row?: Partial<ConditionRow>) => void;
  removeCondition: (ruleId: string, conditionId: string) => void;
  moveCondition: (ruleId: string, conditionId: string, dir: -1 | 1) => void;
  setScoreDelta: (ruleId: string, score_delta: number) => void;
  setTags: (ruleId: string, tags: string[]) => void;
  addRule: () => void;
  setPackMeta: (patch: Partial<Pick<PackDraft, "name" | "mode" | "file">>) => void;
  setJsonText: (text: string) => void;
  applyJsonText: () => { ok: true } | { ok: false; error: string };
  compileForSave: () => unknown;
  reset: () => void;
};

function draftToJsonText(draft: PackDraft): string {
  return JSON.stringify(compilePack(draft), null, 2);
}

function newCondId(): string {
  return `cond_${Math.random().toString(36).slice(2, 10)}`;
}

function newRuleId(): string {
  return `studio_rule_${Math.random().toString(36).slice(2, 10)}`;
}

export const usePackDraftStore = create<PackDraftState>((set, get) => ({
  draft: emptyPackDraft(),
  dirty: false,
  jsonText: draftToJsonText(emptyPackDraft()),

  loadFromJson: (json) => {
    const draft = parsePack(json);
    set({ draft, dirty: false, jsonText: draftToJsonText(draft) });
  },

  hydrateFromServerPack: (pack) => {
    const draft = parsePack(pack);
    set({ draft, dirty: false, jsonText: draftToJsonText(draft) });
  },

  setCondition: (ruleId, conditionId, patch) => {
    const draft = structuredClone(get().draft);
    const rule = draft.rules.find((r) => r.id === ruleId);
    if (!rule) return;
    const cond = rule.when.find((c) => c.id === conditionId);
    if (!cond) return;
    Object.assign(cond, patch);
    set({ draft, dirty: true, jsonText: draftToJsonText(draft) });
  },

  addCondition: (ruleId, row) => {
    const draft = structuredClone(get().draft);
    const rule = draft.rules.find((r) => r.id === ruleId);
    if (!rule) return;
    rule.when.push({
      id: newCondId(),
      field: row?.field ?? "",
      op: row?.op ?? "eq",
      value: row?.value,
    });
    set({ draft, dirty: true, jsonText: draftToJsonText(draft) });
  },

  removeCondition: (ruleId, conditionId) => {
    const draft = structuredClone(get().draft);
    const rule = draft.rules.find((r) => r.id === ruleId);
    if (!rule) return;
    rule.when = rule.when.filter((c) => c.id !== conditionId);
    set({ draft, dirty: true, jsonText: draftToJsonText(draft) });
  },

  moveCondition: (ruleId, conditionId, dir) => {
    const draft = structuredClone(get().draft);
    const rule = draft.rules.find((r) => r.id === ruleId);
    if (!rule) return;
    const idx = rule.when.findIndex((c) => c.id === conditionId);
    const j = idx + dir;
    if (idx < 0 || j < 0 || j >= rule.when.length) return;
    const tmp = rule.when[idx];
    rule.when[idx] = rule.when[j];
    rule.when[j] = tmp;
    set({ draft, dirty: true, jsonText: draftToJsonText(draft) });
  },

  setScoreDelta: (ruleId, score_delta) => {
    const draft = structuredClone(get().draft);
    const rule = draft.rules.find((r) => r.id === ruleId);
    if (!rule) return;
    rule.score_delta = score_delta;
    set({ draft, dirty: true, jsonText: draftToJsonText(draft) });
  },

  setTags: (ruleId, tags) => {
    const draft = structuredClone(get().draft);
    const rule = draft.rules.find((r) => r.id === ruleId);
    if (!rule) return;
    rule.tags = tags;
    set({ draft, dirty: true, jsonText: draftToJsonText(draft) });
  },

  addRule: () => {
    const draft = structuredClone(get().draft);
    draft.rules.push({
      id: newRuleId(),
      when: [{ id: newCondId(), field: "amount", op: "gte", value: 0 }],
      score_delta: 10,
      tags: [],
      description: "",
      rawBlocks: [],
    });
    if (!draft.name) draft.name = "studio_draft";
    if (draft.version === undefined) draft.version = 1;
    if (!draft.mode) draft.mode = "shadow";
    if (draft.tag_rules === undefined) draft.tag_rules = [];
    if (!("canary_percent" in draft)) draft.canary_percent = null;
    if (!("effective_at" in draft)) draft.effective_at = null;
    if (!("approved_by" in draft)) draft.approved_by = null;
    set({ draft, dirty: true, jsonText: draftToJsonText(draft) });
  },

  setPackMeta: (patch) => {
    const draft = { ...get().draft, ...patch };
    set({ draft, dirty: true, jsonText: draftToJsonText(draft) });
  },

  setJsonText: (text) => {
    set({ jsonText: text, dirty: true });
  },

  applyJsonText: () => {
    try {
      const parsed = JSON.parse(get().jsonText) as unknown;
      const draft = parsePack(parsed);
      set({ draft, dirty: true, jsonText: draftToJsonText(draft) });
      return { ok: true as const };
    } catch (e) {
      return { ok: false as const, error: e instanceof Error ? e.message : "Invalid JSON" };
    }
  },

  compileForSave: () => compilePack(get().draft),

  reset: () => {
    const draft = emptyPackDraft();
    set({ draft, dirty: false, jsonText: draftToJsonText(draft) });
  },
}));
