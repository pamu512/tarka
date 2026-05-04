/**
 * Case API helpers — SAR filing transport (Postgres-backed state machine).
 * Core HTTP methods live on {@link cases} in `./client`; this module adds UX-oriented utilities.
 */

import type { SarAuditLogEntry, SarFilingIntentDetail, SarFilingIntentStatus } from "./client";
import { cases } from "./client";

export type { SarAuditLogEntry, SarFilingIntentDetail, SarFilingIntentStatus, SarFilingIntentsResponse } from "./client";

export const sarTransport = {
  listIntents: (caseId: string, tenantId: string) => cases.listSarFilingIntents(caseId, tenantId),
  approveIntent: (caseId: string, tenantId: string, intentId: string) =>
    cases.approveSarFilingIntent(caseId, tenantId, intentId),
  queueTransmit: (caseId: string, tenantId: string, intentId: string) =>
    cases.queueSarFilingSftp(caseId, tenantId, intentId),
};

const ORDERED_STATUSES: readonly SarFilingIntentStatus[] = [
  "PENDING_REVIEW",
  "APPROVED",
  "SFTP_QUEUED",
  "TRANSMITTED",
  "ACKNOWLEDGED",
];

function indexOfStatus(s: string): number {
  return ORDERED_STATUSES.indexOf(s as SarFilingIntentStatus);
}

/**
 * When the intent is `FAILED`, returns the last FAILED audit row's human-readable context
 * (detail fields, validation errors, or stack trace lead-in) for alerts.
 */
export function extractSarFailureMessage(auditLog: SarAuditLogEntry[]): string {
  const failedRows = auditLog.filter((r) => r.to_status === "FAILED");
  const failed = failedRows[failedRows.length - 1];
  if (!failed) {
    return "SAR filing or transport is in a failed state; review the audit trail below.";
  }
  const d = failed.detail && typeof failed.detail === "object" ? failed.detail : {};
  const parts: string[] = [];
  if (typeof d.message === "string" && d.message.trim()) parts.push(d.message.trim());
  if (typeof d.detail === "string" && d.detail.trim()) parts.push(d.detail.trim());
  if (typeof d.reason === "string" && d.reason.trim()) parts.push(d.reason.trim());
  if (typeof d.reason_code === "string" && d.reason_code.trim()) {
    parts.push(`Reason code: ${String(d.reason_code).trim()}`);
  }
  const ve = d.validation_errors;
  if (Array.isArray(ve) && ve.length) {
    parts.push(
      ve
        .map((x) => (typeof x === "string" ? x : JSON.stringify(x)))
        .join("; "),
    );
  }
  if (typeof failed.stack_trace === "string" && failed.stack_trace.trim()) {
    parts.push(failed.stack_trace.trim().split("\n").slice(0, 3).join(" "));
  }
  return (
    parts.filter(Boolean).join(" · ") ||
    "SAR filing or transport failed; review the audit trail and contact engineering if needed."
  );
}

/** Index of the last completed step in the ordered pipeline (-1 if none). */
export function sarStatusStepIndex(status: SarFilingIntentStatus, auditLog: SarAuditLogEntry[]): number {
  if (status === "FAILED") {
    const fail = [...auditLog].reverse().find((r) => r.to_status === "FAILED");
    const from = fail?.from_status as SarFilingIntentStatus | null | undefined;
    if (from && indexOfStatus(from) >= 0) {
      return indexOfStatus(from);
    }
    return -1;
  }
  const i = indexOfStatus(status);
  return i >= 0 ? i : -1;
}

export const SAR_PIPELINE_STEP_LABELS: { status: SarFilingIntentStatus; label: string }[] = [
  { status: "PENDING_REVIEW", label: "Pending review" },
  { status: "APPROVED", label: "Approved" },
  { status: "SFTP_QUEUED", label: "Queued for transmit" },
  { status: "TRANSMITTED", label: "Transmitted" },
  { status: "ACKNOWLEDGED", label: "Acknowledged" },
];
