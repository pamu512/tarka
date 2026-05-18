import {
  normalizeBacktestBlockSeries,
  type BacktestBlockPoint,
  type BacktestBlocksResponse,
} from "./backtestBlockSeries";

export async function fetchHypothesisBacktestBlocks(
  rule: Record<string, unknown>,
  *,
  lookbackDays?: number,
): Promise<BacktestBlockPoint[]> {
  const res = await fetch("/api/v1/hypotheses/backtest-blocks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rule,
      lookback_days: lookbackDays,
    }),
  });
  const body = (await res.json().catch(() => ({}))) as BacktestBlocksResponse & {
    error?: string;
    detail?: string;
  };
  if (!res.ok) {
    const msg =
      typeof body.error === "string"
        ? body.detail
          ? `${body.error}: ${body.detail}`
          : body.error
        : `Backtest blocks failed (${res.status})`;
    throw new Error(msg);
  }
  return normalizeBacktestBlockSeries(body.series);
}
