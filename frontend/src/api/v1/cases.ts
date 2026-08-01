/**
 * Versioned case-api client (`/api/cases/v1/*`).
 *
 * Case Detail / evidence / SAR / dispute UI should import from this module
 * (not the god `client.ts` barrel) as mockData / client continue to shrink.
 */

export {
  cases,
  disputes,
  type Case,
  type DisputeEntry,
  type DisputeStats,
  type SarFilingIntentsResponse,
  type SarIntentDetailResponse,
  toUserFacingApiError,
} from "../client";
