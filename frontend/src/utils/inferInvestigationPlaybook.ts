/** Marketplace COD / courier / payout-hold playbook (investigation-agent catalog). */
export const MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK = "marketplace_cod_courier_hold";

const MARKETPLACE_COD_MARKERS = [
  "vertical:offline_payment",
  "risk:cod_abuse",
  "risk:courier_spoof",
  "risk:promo_farm",
  "action:payout_hold",
  "action:payout_delay",
  "is_cod",
  "is_offline_payment",
] as const;

/**
 * Infer investigation-agent playbook id from decision explain tags / feature flags.
 * Returns null when no marketplace COD/courier/hold signal is present.
 */
export function inferInvestigationPlaybookId(
  tags: readonly string[] | null | undefined,
): string | null {
  if (!tags?.length) return null;
  const normalized = tags.map((t) => String(t).trim().toLowerCase()).filter(Boolean);
  for (const tag of normalized) {
    if (tag.startsWith("vendor:incognia")) return MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK;
    if ((MARKETPLACE_COD_MARKERS as readonly string[]).includes(tag)) {
      return MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK;
    }
    if (tag === "payment_method:cod" || tag.endsWith(":cod")) {
      return MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK;
    }
  }
  return null;
}
