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
  counterCatalog: () => decisions.counterCatalog(),
};
