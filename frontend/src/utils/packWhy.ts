/**
 * Investigator first-open: pack that fired + one plain-language why.
 * Never invent a reason. If the pack reason is absent, the strip still shows "missing".
 */

export const PACK_WHY_MISSING = "missing";

/** Shown only when the case/audit already records an advise timeout. */
export const ADVISE_TIMEOUT_COPY =
  "Advise unavailable (timed out). The pack reason above still stands.";

export type PackWhyView = {
  packId: string;
  packName: string;
  why: string;
  /** LLM advise line. Null means do not render an Advise slot. */
  advise: string | null;
};

export type PackWhySource = {
  rule_pack_file?: string | null;
  pack_id?: string | null;
  pack_name?: string | null;
  pack_reason?: string | null;
  reasons?: readonly string[] | null;
  driver_explain?: ReadonlyArray<{ label?: string; reason?: string }> | null;
  evaluate_payload?: Record<string, unknown> | null;
  advise?: string | null;
  advise_status?: string | null;
  advise_error?: string | null;
  advise_timed_out?: boolean | null;
};

function trimStr(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  return t ? t : null;
}

function firstNonEmpty(...vals: Array<string | null | undefined>): string | null {
  for (const v of vals) {
    const t = trimStr(v);
    if (t) return t;
  }
  return null;
}

/** File stem from `rule_pack_file` (comma-joined contributing packs on the audit snapshot). */
export function packIdFromRulePackFile(rulePackFile: string | null | undefined): string | null {
  const raw = trimStr(rulePackFile);
  if (!raw) return null;
  const parts = raw
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => {
      const base = p.split(/[/\\]/).pop() ?? p;
      return base.replace(/\.json$/i, "") || base;
    });
  return parts.length ? parts.join(", ") : null;
}

function isTechnicalReasoning(text: string): boolean {
  const t = text.trim();
  if (!t || t === "evaluate") return true;
  if (/^rules=/.test(t)) return true;
  if (/^rules:/.test(t)) return true;
  if (/^signals:/.test(t)) return true;
  if (/^ml:/.test(t)) return true;
  if (/^fallback=/.test(t)) return true;
  return false;
}

function firstDriverLabel(
  rows: ReadonlyArray<{ label?: string; reason?: string }> | null | undefined,
): string | null {
  if (!rows?.length) return null;
  for (const row of rows) {
    const label = trimStr(row?.label);
    if (label) return label;
  }
  return null;
}

function payloadAdvise(ep: Record<string, unknown> | null | undefined): {
  text: string | null;
  timedOut: boolean;
} {
  if (!ep || typeof ep !== "object") return { text: null, timedOut: false };
  const status = trimStr(ep.advise_status) ?? trimStr(ep.advise_error);
  const timedOut =
    ep.advise_timed_out === true ||
    (status != null && /timeout|timed[_\s-]?out/i.test(status));
  const text = firstNonEmpty(
    trimStr(ep.advise),
    trimStr(ep.advise_line),
    trimStr(ep.advise_text),
    trimStr(ep.llm_advise),
    trimStr(ep.agent_advise),
  );
  return { text, timedOut };
}

/**
 * Resolve pack id/name + why from fields already on the case audit / evaluate snapshot.
 * Does not synthesize a narrative from ML summary or recommended_action.
 */
export function resolvePackWhy(input: PackWhySource): PackWhyView {
  const ep = input.evaluate_payload && typeof input.evaluate_payload === "object" ? input.evaluate_payload : null;

  const packId =
    firstNonEmpty(
      input.pack_id,
      trimStr(ep?.pack_id),
      packIdFromRulePackFile(input.rule_pack_file),
      packIdFromRulePackFile(trimStr(ep?.rule_pack_file)),
    ) ?? PACK_WHY_MISSING;

  const packName =
    firstNonEmpty(
      input.pack_name,
      trimStr(ep?.pack_name),
      packId === PACK_WHY_MISSING ? null : packId,
    ) ?? PACK_WHY_MISSING;

  const explicitReason = firstNonEmpty(
    input.pack_reason,
    trimStr(ep?.pack_reason),
    trimStr(ep?.pack_why),
  );
  const reasoning = firstNonEmpty(trimStr(ep?.reasoning));
  const reasoningIfPlain = reasoning && !isTechnicalReasoning(reasoning) ? reasoning : null;
  const why =
    firstNonEmpty(explicitReason, reasoningIfPlain, firstDriverLabel(input.driver_explain)) ??
    PACK_WHY_MISSING;

  const fromPayload = payloadAdvise(ep);
  const status = firstNonEmpty(input.advise_status, input.advise_error);
  const timedOut =
    input.advise_timed_out === true ||
    fromPayload.timedOut ||
    (status != null && /timeout|timed[_\s-]?out/i.test(status));
  const adviseText = firstNonEmpty(input.advise, fromPayload.text);

  let advise: string | null = null;
  if (timedOut) {
    advise = ADVISE_TIMEOUT_COPY;
  } else if (adviseText) {
    advise = adviseText;
  }

  return { packId, packName, why, advise };
}
