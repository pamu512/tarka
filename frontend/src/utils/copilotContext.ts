import type { PlatformAuditEvent } from "../api/client";

/** UI + API flags for how platform audit is attached to Investigation Copilot. */
export interface CopilotContextFlags {
  /** When false, no platform audit is sent (privacy / minimal context). */
  trackHistoricalActions: boolean;
  /** When true, only audit rows at or after `sessionStartedAt` are included. */
  onlySession: boolean;
  /** When true, drop noisy rows (copilot usage, session churn). */
  skipSessionActions: boolean;
}

const SESSION_NOISE_RESOURCE = /investigation:copilot|copilot:chat|admin:session|auth:session|admin:sessions/i;
const SESSION_NOISE_DETAIL = /session token|refresh session|sso session|idle session/i;

export function isSessionNoiseAuditRow(e: Pick<PlatformAuditEvent, "resource" | "detail">): boolean {
  const r = (e.resource ?? "").toLowerCase();
  const d = (e.detail ?? "").toLowerCase();
  if (SESSION_NOISE_RESOURCE.test(r)) return true;
  if (SESSION_NOISE_DETAIL.test(d)) return true;
  return false;
}

/**
 * Filter and cap platform audit for the copilot request.
 * Server re-validates; this keeps payloads small and matches analyst choices.
 */
export function buildPlatformAuditForCopilot(
  items: PlatformAuditEvent[],
  flags: CopilotContextFlags,
  sessionStartedAt: string,
  maxItems = 40,
): PlatformAuditEvent[] {
  if (!flags.trackHistoricalActions) return [];

  let out = [...items];

  if (flags.onlySession) {
    const start = Date.parse(sessionStartedAt);
    if (!Number.isNaN(start)) {
      out = out.filter((e) => {
        const t = Date.parse(e.ts);
        return !Number.isNaN(t) && t >= start;
      });
    }
  }

  if (flags.skipSessionActions) {
    out = out.filter((e) => !isSessionNoiseAuditRow(e));
  }

  return out.slice(0, maxItems);
}
