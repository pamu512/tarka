import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { saarthi } from "../../api/client";
import type {
  SaarthiFeatureImportanceRequestBody,
  SaarthiFeatureImportanceResponse,
} from "../../lib/saarthi/featureImportance";
import { toUserFacingError } from "../../utils/userFacingErrors";

const CHART_HEIGHT_PER_ROW = 28;
const CHART_MIN = 200;
const BAR_TOP = "#5eead4";
const BAR_REST = "#334155";

export type SaarthiFeatureImportancePanelProps = {
  /** Stable key so we refetch when the underlying audit snapshot changes. */
  requestKey: string;
  payload: SaarthiFeatureImportanceRequestBody | null;
};

export function SaarthiFeatureImportancePanel({ requestKey, payload }: SaarthiFeatureImportancePanelProps) {
  const [data, setData] = useState<SaarthiFeatureImportanceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!payload || !requestKey) {
      setData(null);
      setError(null);
      setLoading(false);
      return undefined;
    }
    const ac = new AbortController();
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await saarthi.featureImportance(payload, { signal: ac.signal });
        if (!ac.signal.aborted) setData(res);
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        if (!ac.signal.aborted) {
          setData(null);
          setError(
            toUserFacingError(e, { subject: "Saarthi feature importance", action: "rank drivers for this score" }),
          );
        }
      } finally {
        if (!ac.signal.aborted) setLoading(false);
      }
    })();
    return () => ac.abort();
  }, [requestKey, payload]);

  if (!payload) {
    return (
      <section
        id="saarthi-feature-importance"
        aria-label="Feature importance"
        className="rounded-xl border border-surface-700 bg-surface-900/80 px-4 py-3"
      >
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Feature importance (Saarthi)</h3>
        <p className="text-sm text-gray-500">Load a case with a decision audit to rank which signals moved this score.</p>
      </section>
    );
  }

  const chartRows = (data?.items ?? []).map((d) => ({
    ...d,
    labelShort: d.label.length > 42 ? `${d.label.slice(0, 39)}…` : d.label,
  }));
  const chartHeight = Math.min(420, Math.max(CHART_MIN, chartRows.length * CHART_HEIGHT_PER_ROW + 48));

  return (
    <section
      id="saarthi-feature-importance"
      aria-label="Feature importance"
      className="rounded-xl border border-surface-700 bg-surface-900/80 px-4 py-4 space-y-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Feature importance (Saarthi)</h3>
          <p className="text-[11px] text-gray-500 mt-0.5 max-w-3xl leading-snug">
            Relative influence on the <span className="text-gray-300 font-mono tabular-nums">{payload.risk_score.toFixed(1)}</span>
            /100 score for this trace — ranked by Saarthi from the audit inference bundle (not raw SHAP).
          </p>
        </div>
        {data?.attribution_engine === "mock" ? (
          <span className="text-[10px] font-medium uppercase tracking-wide px-2 py-0.5 rounded border border-amber-500/40 text-amber-200/90 shrink-0">
            Dev mock
          </span>
        ) : data?.attribution_engine === "gemini" ? (
          <span className="text-[10px] font-medium uppercase tracking-wide px-2 py-0.5 rounded border border-emerald-500/40 text-emerald-200/90 shrink-0">
            Saarthi live
          </span>
        ) : null}
      </div>

      {loading && !data ? (
        <div className="flex items-center gap-2 text-xs text-gray-400 py-8" aria-busy="true">
          <span className="inline-block size-4 border-2 border-brand-400 border-t-transparent rounded-full animate-spin shrink-0" />
          Asking Saarthi to rank drivers…
        </div>
      ) : null}

      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      {data && chartRows.length > 0 ? (
        <>
          <p className="text-sm text-gray-200 leading-snug border-l-2 border-brand-500/50 pl-3">{data.lead_rationale}</p>
          <div className="w-full" style={{ height: chartHeight }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                layout="vertical"
                data={chartRows}
                margin={{ top: 4, right: 12, left: 4, bottom: 4 }}
                barCategoryGap={6}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                <XAxis type="number" domain={[0, 100]} tick={{ fill: "#94a3b8", fontSize: 11 }} tickCount={6} />
                <YAxis
                  type="category"
                  dataKey="labelShort"
                  width={148}
                  tick={{ fill: "#cbd5e1", fontSize: 11 }}
                  interval={0}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(value) => [`${Number(value ?? 0)}%`, "Relative weight"]}
                  labelFormatter={(_, p) => {
                    const row = p?.[0]?.payload as { label?: string } | undefined;
                    return row?.label ?? "";
                  }}
                />
                <Bar dataKey="importance" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                  {chartRows.map((row, i) => (
                    <Cell key={row.signal_id} fill={i === 0 ? BAR_TOP : BAR_REST} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[10px] text-gray-500 leading-snug">
            Ordering is explanatory for triage; confirm with policy, rules, and systems of record before enforcement
            decisions.
          </p>
        </>
      ) : null}

      {data && chartRows.length === 0 && !loading ? (
        <p className="text-sm text-gray-500">No ranked items returned for this audit.</p>
      ) : null}
    </section>
  );
}
