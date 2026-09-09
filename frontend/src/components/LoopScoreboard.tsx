export type LoopUnknownReasons = {
  join_rate?: string;
  labeled_receipt_rate?: string;
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
  shadow_divergence?: number | null;
  join_rate?: number | null;
  labeled_receipt_rate?: number | null;
  unknown_reasons?: LoopUnknownReasons | null;
};

const JOIN_REASON_EN: Record<string, string> = {
  empty_tenant: "empty tenant",
  no_receipts: "no receipts",
  no_labels: "no labels",
  receipt_store_absent: "receipt store absent",
};

function joinDash(metrics: LoopMetrics, field: keyof LoopUnknownReasons): string {
  const code = metrics.unknown_reasons?.[field] || "";
  return `— ${JOIN_REASON_EN[code] || "not yet available"}`;
}

function pct(v: number | null | undefined): string | null {
  if (v == null || Number.isNaN(v)) return null;
  return `${Math.round(v * 100)}%`;
}

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
  const noLabels = (metrics.fp_count ?? 0) === 0 && metrics.label_latency_hours?.p50 == null;
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
          <dt className="text-gray-500">shadow divergence</dt>
          <dd>{metrics.shadow_divergence == null ? "—" : String(metrics.shadow_divergence)}</dd>
        </div>
        <div>
          <dt className="text-gray-500">join rate</dt>
          <dd data-testid="loop-join-rate">
            {pct(metrics.join_rate) ?? joinDash(metrics, "join_rate")}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">labeled receipt rate</dt>
          <dd data-testid="loop-labeled-receipt-rate">
            {pct(metrics.labeled_receipt_rate) ?? joinDash(metrics, "labeled_receipt_rate")}
          </dd>
        </div>
      </dl>
      <p className="mt-1 text-[11px] text-gray-500" data-testid="bakeoff-help">
        Join-rate fuel for effectiveness, not a CRM. Horizons are tenant policy, not Tarka morals.
      </p>
    </div>
  );
}
