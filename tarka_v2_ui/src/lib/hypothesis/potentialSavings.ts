/**
 * Aggregate blocked transaction amounts for hypothesis "Potential Savings" (Prompt 197).
 */

export function sumBlockedAmounts(amounts: readonly number[]): number {
  let total = 0;
  for (const raw of amounts) {
    if (typeof raw !== "number" || !Number.isFinite(raw) || raw < 0) continue;
    total += raw;
  }
  return total;
}

export function formatPotentialSavings(
  amount: number,
  currency = "USD",
  locale = "en-US",
): string {
  if (!Number.isFinite(amount)) return "—";
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      maximumFractionDigits: amount >= 1000 ? 0 : 2,
    }).format(amount);
  } catch {
    return `${amount.toLocaleString(locale)} ${currency}`;
  }
}
