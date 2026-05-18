/**
 * Parse command-palette input for opening a case.
 * - `acme/case-uuid-or-id` → explicit tenant + case id
 * - `case-uuid-or-id` alone → case id with {@link preferredTenantId}
 */
export function parseCaseOpenInput(
  raw: string,
  preferredTenantId: string,
): { tenantId: string; caseId: string } | null {
  const q = raw.trim();
  if (!q) return null;
  const slash = q.indexOf("/");
  if (slash > 0 && slash < q.length - 1) {
    const tenantId = q.slice(0, slash).trim();
    const caseId = q.slice(slash + 1).trim();
    if (
      /^[a-zA-Z0-9_.-]{1,64}$/.test(tenantId) &&
      /^[a-zA-Z0-9_.-]{4,256}$/.test(caseId)
    ) {
      return { tenantId, caseId };
    }
    return null;
  }
  if (/^[a-zA-Z0-9_.-]{4,256}$/.test(q)) {
    return { tenantId: preferredTenantId || "demo", caseId: q };
  }
  return null;
}

/** Match `/cases/:caseId` (not `/cases` list). */
export function parseCaseDetailRoute(pathname: string): { caseId: string } | null {
  if (!pathname.startsWith("/cases/") || pathname === "/cases") return null;
  const rest = pathname.slice("/cases/".length);
  if (!rest || rest.includes("/")) return null;
  try {
    const caseId = decodeURIComponent(rest);
    if (caseId === "bulk-triage" || caseId === "compare") return null;
    return caseId ? { caseId } : null;
  } catch {
    return null;
  }
}
