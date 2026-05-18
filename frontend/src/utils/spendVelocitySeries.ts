/**
 * Allocate total cohort/tranche spend across UTC hours in proportion to velocity buckets.
 * Used for analyst-facing **estimated** spend velocity sparklines when hourly dollar splits are not persisted.
 */
export function allocateSpendByHour(buckets24: number[], totalSpend: number): number[] {
  if (buckets24.length !== 24) return Array(24).fill(0);
  const sum = buckets24.reduce((a, b) => a + b, 0);
  if (sum <= 0 || !Number.isFinite(totalSpend) || totalSpend <= 0) {
    return Array(24).fill(0);
  }
  return buckets24.map((c) => (c / sum) * totalSpend);
}
