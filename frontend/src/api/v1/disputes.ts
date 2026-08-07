/**
 * Versioned case-api disputes client (`/api/cases/v1/disputes*`).
 *
 * Disputes UI should import from this module (not the god `client.ts` barrel)
 * as mockData / client continue to shrink.
 */

export {
  disputes,
  type DecisionReprocessSnapshot,
  type DisputeAlertState,
  type DisputeDeadlineQueueItem,
  type DisputeDeadlineQueueResponse,
  type DisputeEntry,
  type DisputeReprocessExternalResponse,
  type DisputeStats,
} from "../client";
