/** Threshold aligned with integration-ingress synthetic identity detectors (Prompt 181). */
export const SYNTHETIC_IDENTITY_FLAG_SCORE = 70;

export function isSyntheticIdentityFlagged(
  riskScore: number | null | undefined,
  isSynthetic?: boolean | null,
): boolean {
  if (isSynthetic === true) return true;
  if (isSynthetic === false) return false;
  return typeof riskScore === "number" && riskScore >= SYNTHETIC_IDENTITY_FLAG_SCORE;
}
