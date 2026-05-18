/**
 * Outcome attribution for rules that appear in decision audit ``rule_hits``.
 * When multiple rules fire on one decision, each rule is credited for that outcome (standard multi-label attribution).
 */

export type RuleOutcomeRow = {
  rule_id: string;
  /** This rule fired and the final decision was **deny** (fraud blocked / hard stop). */
  deny_count: number;
  /** This rule fired and the final decision was **review** (queue for analyst). */
  review_count: number;
  allow_count: number;
  /** Decisions where this rule_id appeared in ``rule_hits``. */
  hit_decisions: number;
};

/**
 * Heuristic: Rust engine rules in this repo often use an ``rs_`` prefix or ``namespace::`` paths in traces.
 * JSON pack rules are typically plain slugs (e.g. ``velocity_guard``). The backend may standardize later.
 */
export function isRustStyleRuleId(ruleId: string): boolean {
  const id = ruleId.trim();
  if (id.length === 0) return false;
  if (id.startsWith("rs_")) return true;
  if (id.startsWith("rust_")) return true;
  if (id.startsWith("tarka_rs::") || id.startsWith("tarka_core::")) return true;
  if (id.includes("::") && !id.toLowerCase().includes("json")) return true;
  return false;
}

export function inferRuleEngine(ruleId: string): "rust" | "json_pack" | "unknown" {
  if (isRustStyleRuleId(ruleId)) return "rust";
  if (/[./]/.test(ruleId) && ruleId.includes("pack")) return "json_pack";
  return "unknown";
}

export function aggregateRuleOutcomes(
  entries: Array<{ decision: string; rule_hits: string[] }>,
): RuleOutcomeRow[] {
  const map = new Map<string, { deny: number; review: number; allow: number }>();

  for (const e of entries) {
    const hits = e.rule_hits ?? [];
    if (hits.length === 0) continue;
    const dec = String(e.decision ?? "").toLowerCase();
    for (const rid of hits) {
      const rule_id = String(rid).trim();
      if (!rule_id) continue;
      if (!map.has(rule_id)) map.set(rule_id, { deny: 0, review: 0, allow: 0 });
      const o = map.get(rule_id)!;
      if (dec === "deny") o.deny += 1;
      else if (dec === "review") o.review += 1;
      else if (dec === "allow") o.allow += 1;
    }
  }

  return [...map.entries()]
    .map(([rule_id, o]) => ({
      rule_id,
      deny_count: o.deny,
      review_count: o.review,
      allow_count: o.allow,
      hit_decisions: o.deny + o.review + o.allow,
    }))
    .sort((a, b) => b.hit_decisions - a.hit_decisions);
}

export function filterRulesByEngine(rows: RuleOutcomeRow[], rustOnly: boolean): RuleOutcomeRow[] {
  if (!rustOnly) return rows;
  return rows.filter((r) => isRustStyleRuleId(r.rule_id));
}

export function topByDeny(rows: RuleOutcomeRow[], limit: number): RuleOutcomeRow[] {
  return [...rows].sort((a, b) => b.deny_count - a.deny_count).slice(0, limit);
}

export function topByReview(rows: RuleOutcomeRow[], limit: number): RuleOutcomeRow[] {
  return [...rows].sort((a, b) => b.review_count - a.review_count).slice(0, limit);
}
