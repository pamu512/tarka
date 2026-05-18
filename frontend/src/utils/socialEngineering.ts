/** Default credential burst window (minutes) — aligned with integration-ingress (Prompt 184). */
export const SOCIAL_ENGINEERING_WINDOW_MINUTES = 10;

export function isSocialEngineeringFlagged(
  flagged?: boolean | null,
  signals?: string[] | null,
): boolean {
  if (flagged === true) return true;
  return Boolean(signals?.includes("social_engineering_credential_burst"));
}
