/**
 * Versioned decision-api client (`/api/decisions/v1/*`).
 *
 * Decision and ops UI should import from this module (not the god `client.ts` barrel)
 * so the surface stays contract-scoped as mockData / client continue to shrink.
 */

export {
  decisions,
  type AuditEntry,
  type AuditExplorerResponse,
  type AuditRecentItem,
  type AuditRecentResponse,
  type DecisionApiSloResponse,
  type DecisionRequest,
  type DecisionResponse,
  type DriftQueryResponse,
  type EvaluationPostureResponse,
  type RuleReplayRequestPayload,
  type RuleReplayResponse,
  type RuleReplayRulePayload,
  type TenantBenchmarkExport,
} from "../client";

import { decisions } from "../client";

/** Ops / trust readiness helpers — thin aliases for versioned imports. */
export const decisionsOps = {
  evaluationPosture: () => decisions.evaluationPosture(),
  slo: () => decisions.slo(),
  governance: () => decisions.governance(),
  challengePolicies: () => decisions.challengePolicies(),
  policyPosture: () => decisions.policyPosture(),
  calibrationStatus: (tenantId: string, profile?: string) =>
    decisions.calibrationStatus(tenantId, profile),
  reliabilityBins: (tenantId: string, limit?: number, nBins?: number) =>
    decisions.reliabilityBins(tenantId, limit, nBins),
  reliabilityExportCsv: (tenantId: string, limit?: number) =>
    decisions.reliabilityExportCsv(tenantId, limit),
  verticalCalibrationPosture: () => decisions.verticalCalibrationPosture(),
  verticalPromotePosture: () => decisions.verticalPromotePosture(),
  trendDrafts: (tenantId: string) => decisions.trendDrafts(tenantId),
  trendTick: (body: {
    tenant_id?: string;
    limit?: number;
    skip_llm?: boolean;
    entity_ids?: string[];
  }) => decisions.trendTick(body),
  trendRejectDraft: (draftId: string, tenantId: string) =>
    decisions.trendRejectDraft(draftId, tenantId),
  trendHilOverride: (body: {
    tenant_id: string;
    entity_id: string;
    override_type: string;
    scope_key?: string;
    analyst_rationale?: string;
  }) => decisions.trendHilOverride(body),
  trendPosture: (tenantId?: string) => decisions.trendPosture(tenantId),
  counterCatalog: () => decisions.counterCatalog(),
};
