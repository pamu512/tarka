import { isApiRequestError, type AuditEntry } from "../api/client";

export type AuditGetter = (
  traceId: string,
  tenantId: string,
  opts?: { detail_level?: "minimal" | "analyst" | "full" },
) => Promise<AuditEntry>;

export function isAuditDetailForbidden(error: unknown): boolean {
  if (isApiRequestError(error) && error.status === 403) return true;
  const raw = error instanceof Error ? error.message : String(error ?? "");
  return /^\s*403\b/.test(raw);
}

/** Analyst first; lite/viewer 403 falls back to minimal (pack-why still present). */
export async function getAuditForPackWhy(
  getAudit: AuditGetter,
  traceId: string,
  tenantId: string,
): Promise<AuditEntry> {
  try {
    return await getAudit(traceId, tenantId, { detail_level: "analyst" });
  } catch (error) {
    if (!isAuditDetailForbidden(error)) throw error;
    return await getAudit(traceId, tenantId, { detail_level: "minimal" });
  }
}
