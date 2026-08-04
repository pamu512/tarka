/**
 * Versioned case-api client (`/api/cases/v1/*`).
 *
 * Case Detail / evidence / SAR UI should import from this module
 * (not the god `client.ts` barrel). Disputes list/detail prefer `api/v1/disputes`.
 */

export {
  cases,
  disputes,
  type Case,
  type CaseCreateRequest,
  type CaseDeskActivity,
  type CaseOpsKpis,
  type DisputeEntry,
  type DisputeStats,
  type SarFilingIntentsResponse,
  type SarIntentDetailResponse,
  type SarTransportBoardCard,
  type SarTransportBoardResponse,
  toUserFacingApiError,
} from "../client";
