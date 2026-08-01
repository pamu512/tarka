/**
 * Compact "act pack" from a case evidence bundle + optional live explain row.
 * Analysts copy this into SAR/dispute notes; not a new server schema.
 */

export type EvidenceActPack = {
  schema_id: "tarka.evidence_act_pack/v1";
  case_id: string;
  tenant_id: string;
  entity_id: string;
  trace_id: string | null;
  content_sha256: string | null;
  decision: string | null;
  score: number | null;
  recommended_action: string | null;
  confidence_tier: string | null;
  top_drivers: string[];
  suggested_next: Array<"sar_generate" | "dispute_open" | "manual_review">;
};

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

export function buildEvidenceActPack(
  bundle: Record<string, unknown>,
  opts?: {
    decisionExplain?: {
      decision?: string;
      score?: number;
      recommended_action?: string | null;
      inference_context?: {
        confidence_tier?: string;
        driver_reasons?: string[];
      } | null;
    } | null;
  },
): EvidenceActPack {
  const caseRow = asRecord(bundle.case);
  const audit = asRecord(bundle.decision_audit);
  const v1 = asRecord(bundle.evidence_bundle_v1);
  const explain = opts?.decisionExplain ?? null;
  const inf = explain?.inference_context ?? null;

  const decision =
    (explain?.decision != null ? String(explain.decision) : null) ||
    (audit?.decision != null ? String(audit.decision) : null) ||
    (audit?.rule_result != null ? String(audit.rule_result) : null);

  const scoreRaw = explain?.score ?? audit?.score;
  let score: number | null = null;
  if (typeof scoreRaw === "number" && Number.isFinite(scoreRaw)) score = scoreRaw;
  else if (scoreRaw != null) {
    const n = Number(scoreRaw);
    if (Number.isFinite(n)) score = n;
  }

  const recommended =
    (explain?.recommended_action != null && String(explain.recommended_action).trim() !== ""
      ? String(explain.recommended_action)
      : null) ||
    (audit?.recommended_action != null ? String(audit.recommended_action) : null);

  const drivers = inf?.driver_reasons ?? [];

  // Always offer both primary act paths; add manual_review when policy suggests it.
  const suggested: EvidenceActPack["suggested_next"] = ["sar_generate", "dispute_open"];
  const ra = (recommended || "").toLowerCase();
  if (ra.includes("manual") || ra.includes("review")) {
    suggested.push("manual_review");
  }
  const uniq = [...new Set(suggested)];

  return {
    schema_id: "tarka.evidence_act_pack/v1",
    case_id: String(caseRow?.id ?? ""),
    tenant_id: String(bundle.tenant_id ?? caseRow?.tenant_id ?? ""),
    entity_id: String(caseRow?.entity_id ?? ""),
    trace_id: caseRow?.trace_id != null ? String(caseRow.trace_id) : null,
    content_sha256: v1?.content_sha256 != null ? String(v1.content_sha256) : null,
    decision,
    score,
    recommended_action: recommended,
    confidence_tier: inf?.confidence_tier != null ? String(inf.confidence_tier) : null,
    top_drivers: drivers.map(String).slice(0, 8),
    suggested_next: uniq,
  };
}
