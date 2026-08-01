/**
 * Versioned case-api disputes client (`/api/cases/v1/disputes*`).
 *
 * Disputes UI should import from this module (not the god `client.ts` barrel)
 * as mockData / client continue to shrink.
 */

export {
  disputes,
  type DisputeEntry,
  type DisputeStats,
} from "../client";
