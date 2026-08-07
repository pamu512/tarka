import type { DecisionExplain } from "../context/CaseWorkbenchContext";

/** Fields safe to share with support / customer for FP explanations (no raw payload PII). */
export function buildSupportSafeSummary(input: {
  caseId: string;
  tenantId: string;
  entityId: string;
  traceId: string;
  status: string;
  labels: string[];
  decisionExplain: DecisionExplain | null;
}): string {
  const d = input.decisionExplain;
  const disposition = (input.labels || [])
    .filter((l) => l.startsWith("disposition:"))
    .map((l) => l.slice("disposition:".length));
  const lines = [
    "## Support-safe case summary",
    "",
    `Case ID: ${input.caseId}`,
    `Tenant: ${input.tenantId}`,
    `Entity ID: ${input.entityId}`,
    `Trace ID: ${input.traceId || "(none)"}`,
    `Status: ${input.status}`,
    disposition.length ? `Disposition reason: ${disposition.join(", ")}` : null,
    "",
    "### Decision (safe fields)",
    d
      ? [
          `Decision: ${d.decision}`,
          `Score: ${d.score}`,
          `Rule hits: ${(d.rule_hits || []).join(", ") || "(none)"}`,
          `Tags: ${(d.tags || []).slice(0, 12).join(", ") || "(none)"}`,
          d.recommended_action ? `Recommended action: ${d.recommended_action}` : null,
          d.inference_context?.ml_summary
            ? `ML summary: ${String(d.inference_context.ml_summary).slice(0, 280)}`
            : null,
        ]
          .filter(Boolean)
          .join("\n")
      : "(decision audit unavailable)",
    "",
    "### Do not share",
    "- Raw evaluate payload / PII fields",
    "- Full graph neighborhood dumps",
    "- Internal SAR investigative notes",
    "",
    "### Suggested customer wording (edit before send)",
    "We reviewed this decision using our risk controls. If this was a false positive,",
    "we can clear the hold after a second review. Reference the Case ID and Trace ID above",
    "when contacting support so we can locate the audited decision.",
  ];
  return lines.filter((x) => x !== null).join("\n");
}
