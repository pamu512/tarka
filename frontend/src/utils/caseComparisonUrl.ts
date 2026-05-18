/** Build URL for side-by-side case comparison (Prompt 168). */
export function buildCaseComparisonHref(params: {
  tenantId: string;
  caseA?: string;
  caseB?: string;
}): string {
  const sp = new URLSearchParams();
  sp.set("tenant_id", params.tenantId.trim() || "demo");
  const a = params.caseA?.trim();
  const b = params.caseB?.trim();
  if (a) sp.set("case_a", a);
  if (b) sp.set("case_b", b);
  return `/cases/compare?${sp}`;
}
