/**
 * Map ``metrics_json`` from a completed warehouse backtest job into Recharts rows.
 * Prefers ``chart_series`` (written per OLAP chunk in ``run_backtest_job``); falls back to a single
 * aggregate point when only final rates exist (older jobs).
 */

export type BacktestChartRow = {
  chunk_index: number;
  rows_processed: number;
  false_positive_rate: number;
  precision: number;
  recall: number;
  /** X-axis label */
  label: string;
};

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

export function mapBacktestMetricsToChartRows(metrics: unknown): BacktestChartRow[] {
  if (!metrics || typeof metrics !== "object") return [];
  const m = metrics as Record<string, unknown>;
  const series = m.chart_series;
  if (Array.isArray(series) && series.length > 0) {
    return series.map((raw, i) => {
      const p = raw as Record<string, unknown>;
      const idx = Number(p.chunk_index ?? i);
      return {
        chunk_index: Number.isFinite(idx) ? idx : i,
        rows_processed: Number(p.rows_processed ?? 0),
        false_positive_rate: clamp01(Number(p.false_positive_rate)),
        precision: clamp01(Number(p.precision)),
        recall: clamp01(Number(p.recall)),
        label: `Chunk ${Number.isFinite(idx) ? idx : i}`,
      };
    });
  }

  const fpr = Number(m.false_positive_rate);
  const pr = Number(m.precision);
  const rc = Number(m.recall);
  if (Number.isFinite(fpr) && Number.isFinite(pr) && Number.isFinite(rc)) {
    return [
      {
        chunk_index: 0,
        rows_processed: Number(m.rows_processed ?? 0),
        false_positive_rate: clamp01(fpr),
        precision: clamp01(pr),
        recall: clamp01(rc),
        label: "Final",
      },
    ];
  }

  return [];
}

export function isTerminalBacktestStatus(status: string | undefined | null): boolean {
  const s = (status ?? "").toUpperCase();
  return s === "SUCCEEDED" || s.startsWith("FAILED");
}

export function isPendingBacktestStatus(status: string | undefined | null): boolean {
  const s = (status ?? "").toUpperCase();
  return s === "PENDING" || s === "RUNNING";
}
