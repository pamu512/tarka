export type LoopMetrics = {
  leftover_to_draft_ms?: { p50?: number | null; p95?: number | null };
  drafts_to_observe?: { human?: number; ai?: number };
  ai_backtest_block_rate?: number | null;
  fp_count?: number;
  fp_cost_sum?: number;
  label_latency_ms?: { p50?: number | null };
  promote_ttl_ms?: { p50?: number | null };
};

function num(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return String(Math.round(v));
}

export function LoopScoreboard({ metrics }: { metrics: LoopMetrics | null }) {
  if (!metrics) {
    return (
      <p data-testid="loop-scoreboard" className="text-xs text-gray-500">
        Loop metrics unavailable.
      </p>
    );
  }
  const drafts = metrics.drafts_to_observe || {};
  return (
    <dl
      data-testid="loop-scoreboard"
      className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-gray-300 border border-surface-600 rounded-lg p-3"
    >
      <div>
        <dt className="text-gray-500">leftover→draft p50 ms</dt>
        <dd>{num(metrics.leftover_to_draft_ms?.p50)}</dd>
      </div>
      <div>
        <dt className="text-gray-500">drafts to Observe</dt>
        <dd>
          human {drafts.human ?? 0} / AI {drafts.ai ?? 0}
        </dd>
      </div>
      <div>
        <dt className="text-gray-500">AI backtest block rate</dt>
        <dd>
          {metrics.ai_backtest_block_rate == null
            ? "—"
            : `${Math.round(metrics.ai_backtest_block_rate * 100)}%`}
        </dd>
      </div>
      <div>
        <dt className="text-gray-500">FP count / cost</dt>
        <dd>
          {metrics.fp_count ?? 0} / {num(metrics.fp_cost_sum)}
        </dd>
      </div>
      <div>
        <dt className="text-gray-500">label latency p50 ms</dt>
        <dd>{num(metrics.label_latency_ms?.p50)}</dd>
      </div>
      <div>
        <dt className="text-gray-500">promote TTL p50 ms</dt>
        <dd>{num(metrics.promote_ttl_ms?.p50)}</dd>
      </div>
    </dl>
  );
}
