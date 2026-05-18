import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BacktestJobStatusResponse } from "../api/client";
import { mapBacktestMetricsToChartRows } from "../utils/backtestMetrics";

function pctFmt(v: number | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

export function BacktestResultsDashboard({ job }: { job: BacktestJobStatusResponse }) {
  const status = (job.status ?? "").toUpperCase();
  const chartData = useMemo(() => mapBacktestMetricsToChartRows(job.metrics), [job.metrics]);

  const failed = status.startsWith("FAILED");
  const pending = !failed && (status === "PENDING" || status === "RUNNING");
  const succeeded = status === "SUCCEEDED";

  if (pending) {
    return (
      <div
        className="rounded-xl border border-amber-500/25 bg-amber-950/15 px-6 py-10 text-center"
        role="status"
        aria-live="polite"
      >
        <div className="mx-auto mb-4 h-10 w-10 border-2 border-amber-400/80 border-t-transparent rounded-full animate-spin" />
        <h3 className="text-lg font-semibold text-amber-100">Job pending</h3>
        <p className="mt-2 text-sm text-amber-200/80 max-w-lg mx-auto">
          The warehouse backtest is queued or streaming rows. Metrics and charts appear when the job reaches{" "}
          <code className="text-amber-100/90">SUCCEEDED</code> and <code className="text-amber-100/90">metrics_json</code> is populated.
        </p>
        <p className="mt-3 text-xs text-amber-200/60 font-mono">job_id {job.job_id}</p>
      </div>
    );
  }

  if (failed) {
    return (
      <div className="rounded-xl border border-rose-500/35 bg-rose-950/20 px-6 py-8" role="alert">
        <h3 className="text-lg font-semibold text-rose-100">Job failed</h3>
        <p className="mt-1 text-sm text-rose-200/90">
          Status <span className="font-mono text-rose-50">{job.status}</span>
          {job.rows_processed != null ? (
            <>
              {" "}
              · rows processed: <span className="font-mono">{job.rows_processed}</span>
            </>
          ) : null}
        </p>
        {job.error_detail ? (
          <pre className="mt-4 max-h-48 overflow-auto rounded-lg border border-rose-500/20 bg-surface-950/80 p-3 text-xs text-rose-100/95 whitespace-pre-wrap">
            {job.error_detail}
          </pre>
        ) : (
          <p className="mt-4 text-sm text-rose-200/70">No error detail was returned for this job.</p>
        )}
      </div>
    );
  }

  if (!succeeded) {
    return (
      <div className="rounded-xl border border-surface-600 bg-surface-900/40 px-6 py-8 text-sm text-gray-400">
        Unknown status <span className="font-mono text-gray-200">{job.status}</span>. Refresh job status to update.
      </div>
    );
  }

  if (chartData.length === 0) {
    return (
      <div className="rounded-xl border border-surface-600 bg-surface-900/40 px-6 py-8 text-center text-sm text-gray-400">
        Job finished, but no <code className="text-gray-300">chart_series</code> or aggregate rates were found in{" "}
        <code className="text-gray-300">metrics</code>. If no rows were evaluated, run a larger window or verify analytics data.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-gray-100">Results over streaming chunks</h3>
          <p className="mt-1 text-xs text-gray-500">
            Lines show running false-positive rate (among historical allows), precision, and recall after each OLAP chunk (
            <code className="text-gray-400">metrics_json.chart_series</code>).
          </p>
        </div>
        <div className="text-right text-xs text-gray-500 tabular-nums">
          <div>rows processed: {job.rows_processed}</div>
          {chartData.length ? <div>points: {chartData.length}</div> : null}
        </div>
      </div>

      <div className="h-[340px] w-full min-h-[280px] rounded-xl border border-surface-700 bg-surface-950/50 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="chunk_index"
              stroke="#94a3b8"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              label={{ value: "Chunk index", position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 11 }}
            />
            <YAxis
              domain={[0, 1]}
              stroke="#94a3b8"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`}
              width={44}
            />
            <Tooltip
              contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
              labelStyle={{ color: "#e2e8f0" }}
              formatter={(value, name) => [
                pctFmt(typeof value === "number" ? value : Number(value ?? 0)),
                String(name),
              ]}
              labelFormatter={(label) => `Chunk ${label}`}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey="false_positive_rate"
              name="False-positive rate"
              stroke="#fb7185"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="precision"
              name="Precision"
              stroke="#60a5fa"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="recall"
              name="Recall"
              stroke="#4ade80"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
