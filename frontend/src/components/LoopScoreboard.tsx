export type LoopUnknownReasons = {
  evaluate_count?: string;
  action_mix?: string;
  shadow_divergence?: string;
};

export type LoopMetrics = {
  leftover_to_draft_ms?: { p50?: number | null; p95?: number | null };
  drafts_to_observe?: { human?: number; ai?: number };
  leftover_mint_rate?: number | null;
  ai_backtest_block_rate?: number | null;
  fp_count?: number;
  fp_cost_sum?: number;
  label_latency_ms?: { p50?: number | null };
  label_latency_hours?: { p50?: number | null };
  promote_ttl_ms?: { p50?: number | null };
  promote_ttl_hours?: { p50?: number | null };
  demote_propose_count?: number;
  demote_confirm_count?: number;
  evaluate_count?: number | null;
  action_mix?: Record<string, number> | null;
  shadow_divergence?: number | null;
  reason_code?: string | null;
  unknown_reasons?: LoopUnknownReasons | null;
};

const UNKNOWN_REASON_EN: Record<string, string> = {
  evaluate_store_absent: "no audit in window",
  no_shadow_live_pairs: "no Observe/live pairs in window",
  empty_tenant: "empty tenant",
  not_computed: "metrics not yet available",
};

type UnknownField = keyof LoopUnknownReasons;

function reasonEnglish(metrics: LoopMetrics, field: UnknownField): string {
  const code = metrics.unknown_reasons?.[field] || metrics.reason_code || "not_computed";
  return UNKNOWN_REASON_EN[code] || "metrics not yet available";
}

function dashReason(metrics: LoopMetrics, field: UnknownField): string {
  return `— ${reasonEnglish(metrics, field)}`;
}

function num(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return String(Math.round(v));
}

function actionMixLine(mix: Record<string, number> | null | undefined): string | null {
  if (mix == null) return null;
  const parts = Object.entries(mix).filter(([, n]) => typeof n === "number" && !Number.isNaN(n));
  if (parts.length === 0) return null;
  return parts.map(([action, n]) => `${action} ${n}`).join(" · ");
}

/**
 * Parent-fed. OpsShadow refetches `loopMetrics` on tenantId, clears first, and
 * passes `loading` so this board never keeps another tenant's numbers.
 */
export function LoopScoreboard({
  metrics,
  loading = false,
  error = false,
}: {
  metrics: LoopMetrics | null;
  loading?: boolean;
  error?: boolean;
}) {
  if (loading) {
    return (
      <p data-testid="loop-scoreboard" className="text-xs text-gray-500">
        Loading loop metrics.
      </p>
    );
  }
  if (error || !metrics) {
    return (
      <p data-testid="loop-scoreboard" className="text-xs text-gray-500">
        Loop metrics unavailable.
      </p>
    );
  }
  const drafts = metrics.drafts_to_observe || {};
  const noLabels = (metrics.fp_count ?? 0) === 0 && metrics.label_latency_hours?.p50 == null;
  const mixLine = actionMixLine(metrics.action_mix);
  return (
    <div>
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
            {noLabels ? "no labels yet" : `${metrics.fp_count ?? 0} / ${num(metrics.fp_cost_sum)}`}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">label latency p50 h</dt>
          <dd>{metrics.label_latency_hours?.p50 == null ? "—" : metrics.label_latency_hours.p50.toFixed(2)}</dd>
        </div>
        <div>
          <dt className="text-gray-500">promote TTL p50 h</dt>
          <dd>{metrics.promote_ttl_hours?.p50 == null ? "—" : metrics.promote_ttl_hours.p50.toFixed(2)}</dd>
        </div>
        <div>
          <dt className="text-gray-500">demote propose / confirm</dt>
          <dd>
            {metrics.demote_propose_count ?? 0} / {metrics.demote_confirm_count ?? 0}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">evaluate count</dt>
          <dd data-testid="loop-evaluate-count">
            {metrics.evaluate_count == null
              ? dashReason(metrics, "evaluate_count")
              : String(metrics.evaluate_count)}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">action mix</dt>
          <dd data-testid="loop-action-mix">
            {mixLine ?? dashReason(metrics, "action_mix")}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">shadow divergence</dt>
          <dd data-testid="loop-shadow-divergence">
            {metrics.shadow_divergence == null
              ? dashReason(metrics, "shadow_divergence")
              : String(metrics.shadow_divergence)}
          </dd>
        </div>
      </dl>
      <p className="mt-1 text-[11px] text-gray-500" data-testid="bakeoff-help">
        Loop metrics inform Promote. Thresholds are tenant policy, not Tarka morals.
      </p>
    </div>
  );
}
