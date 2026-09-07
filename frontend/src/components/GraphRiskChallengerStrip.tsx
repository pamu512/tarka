export type GraphRiskChallenger = {
  schema_id?: string;
  display_name?: string;
  subtitle?: string;
  graph_hop?: string;
  overlay_url?: string;
  state?: string;
  receipt_count?: number;
  labeled_rows?: number;
  labeled_pct?: number;
  trainable_rows?: number;
  trainable_pct?: number;
  ready_to_train?: boolean;
  p90_label_lag_seconds?: number | null;
  bars?: {
    min_trainable_rows?: number;
    planning_min_labels?: number;
    planning_min_edged_events?: number;
  };
  last_gate?: {
    serve_allowed?: boolean | null;
    model_auc?: number | null;
    heuristic_auc?: number | null;
    reason?: string | null;
  };
  gnn_claim_allowed?: boolean;
  live_effect?: string;
  note?: string;
};

function pct(v: number | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}

export function GraphRiskChallengerStrip({
  data,
  err,
}: {
  data: GraphRiskChallenger | null;
  err?: string | null;
}) {
  if (err) {
    return (
      <p data-testid="graph-risk-challenger" className="text-xs text-amber-400">
        {err}
      </p>
    );
  }
  if (!data) {
    return (
      <p data-testid="graph-risk-challenger" className="text-xs text-gray-500">
        Graph-risk challenger readiness loading…
      </p>
    );
  }
  const gate = data.last_gate || {};
  return (
    <section
      data-testid="graph-risk-challenger"
      className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-3"
    >
      <div>
        <h2 className="text-sm font-semibold text-gray-200">
          {data.display_name || "Graph-risk / Ring-score challenger"}
        </h2>
        <p className="text-xs text-gray-500 mt-1">{data.subtitle}</p>
      </div>
      <dl className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-gray-300">
        <div>
          <dt className="text-gray-500">Graph hop</dt>
          <dd>{data.graph_hop || "—"}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Overlay URL</dt>
          <dd>{data.overlay_url || "empty"}</dd>
        </div>
        <div>
          <dt className="text-gray-500">State</dt>
          <dd>{data.state || "—"}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Trainable / labeled</dt>
          <dd>
            {data.trainable_rows ?? 0} / {data.labeled_rows ?? 0} ({pct(data.trainable_pct)})
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">Labeled % of receipts</dt>
          <dd>{pct(data.labeled_pct)}</dd>
        </div>
        <div>
          <dt className="text-gray-500">p90 label lag (s)</dt>
          <dd>
            {data.p90_label_lag_seconds == null
              ? "—"
              : Math.round(data.p90_label_lag_seconds)}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">Bar: min trainable</dt>
          <dd>
            {data.trainable_rows ?? 0} / {data.bars?.min_trainable_rows ?? 8}
            {data.ready_to_train ? " (ready)" : " (collecting)"}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">Last gate</dt>
          <dd>
            serve={String(gate.serve_allowed)} · model=
            {gate.model_auc == null ? "—" : Number(gate.model_auc).toFixed(2)} · heur=
            {gate.heuristic_auc == null ? "—" : Number(gate.heuristic_auc).toFixed(2)}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">Live effect</dt>
          <dd>{data.live_effect || "pack_promote_only"}</dd>
        </div>
      </dl>
      <p className="text-[11px] text-gray-500">
        {data.note ||
          "Empty overlay URL is evaluate-only. Model never ALLOW/DENY/Promote. Not a live deep-graph model."}
      </p>
    </section>
  );
}
