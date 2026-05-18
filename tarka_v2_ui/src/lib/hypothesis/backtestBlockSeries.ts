/**
 * Visual backtest overlay series (Prompt 198): production vs shadow blocks per time bucket.
 */

export type BacktestBlockPoint = {
  /** ISO-ish bucket key from backend */
  bucket: string;
  /** X-axis label */
  label: string;
  production_blocks: number;
  shadow_blocks: number;
  shadow_only_blocks: number;
};

export type BacktestBlocksResponse = {
  lookback_days?: number;
  series: BacktestBlockPoint[];
};

export function formatBucketLabel(bucket: string): string {
  const trimmed = bucket.trim();
  if (!trimmed) return bucket;
  const normalized = trimmed.includes("T") ? trimmed : trimmed.replace(" ", "T");
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return trimmed;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function normalizeBacktestBlockSeries(raw: unknown): BacktestBlockPoint[] {
  if (!Array.isArray(raw)) return [];
  const out: BacktestBlockPoint[] = [];
  for (const row of raw) {
    if (!row || typeof row !== "object") continue;
    const p = row as Record<string, unknown>;
    const bucket = String(p.bucket ?? p.label ?? "");
    if (!bucket) continue;
    const production = Number(p.production_blocks ?? 0);
    const shadow = Number(p.shadow_blocks ?? 0);
    const shadowOnly = Number(
      p.shadow_only_blocks ?? Math.max(0, shadow - Math.min(shadow, production)),
    );
    out.push({
      bucket,
      label: String(p.label ?? formatBucketLabel(bucket)),
      production_blocks: Number.isFinite(production) ? production : 0,
      shadow_blocks: Number.isFinite(shadow) ? shadow : 0,
      shadow_only_blocks: Number.isFinite(shadowOnly) ? shadowOnly : 0,
    });
  }
  return out.map((row) => ({
    ...row,
    label: row.label || formatBucketLabel(row.bucket),
  }));
}

export function totalShadowOnlyBlocks(series: readonly BacktestBlockPoint[]): number {
  return series.reduce((sum, row) => sum + row.shadow_only_blocks, 0);
}
