"use client";

import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  normalizeBacktestBlockSeries,
  totalShadowOnlyBlocks,
  type BacktestBlockPoint,
} from "@/lib/hypothesis/backtestBlockSeries";

export type BacktestVisualizerProps = {
  /** Hourly (or bucketed) production vs shadow block counts. */
  series: BacktestBlockPoint[] | unknown;
  className?: string;
  height?: number;
  lookbackDays?: number;
};

type ChartRow = BacktestBlockPoint & { index: number };

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; color?: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-slate-600 bg-slate-950/95 px-3 py-2 text-xs shadow-lg">
      <p className="mb-1.5 font-semibold text-slate-200">{label}</p>
      <ul className="space-y-1">
        {payload.map((entry) => (
          <li key={String(entry.name)} className="flex justify-between gap-4 tabular-nums">
            <span style={{ color: entry.color }}>{entry.name}</span>
            <span className="font-mono text-slate-100">{entry.value ?? 0}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BacktestVisualizer({
  series,
  className = "",
  height = 320,
  lookbackDays = 7,
}: BacktestVisualizerProps) {
  const normalized = useMemo(() => normalizeBacktestBlockSeries(series), [series]);
  const chartData = useMemo<ChartRow[]>(
    () => normalized.map((row, index) => ({ ...row, index })),
    [normalized],
  );
  const shadowOnlyTotal = useMemo(() => totalShadowOnlyBlocks(normalized), [normalized]);

  if (chartData.length === 0) {
    return (
      <div
        className={[
          "rounded-lg border border-slate-700 bg-slate-900/40 px-4 py-8 text-center text-sm text-slate-500",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        data-testid="backtest-visualizer-empty"
      >
        No block timeline data for the last {lookbackDays} days. Run a DuckDB backtest to populate the
        overlay.
      </div>
    );
  }

  return (
    <section
      className={["space-y-3", className].filter(Boolean).join(" ")}
      aria-label="Production vs shadow block overlay"
      data-testid="backtest-visualizer"
    >
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold uppercase tracking-[0.18em] text-slate-200">
            Visual backtest
          </h3>
          <p className="mt-1 max-w-xl text-xs leading-relaxed text-slate-500">
            Overlay compares <span className="text-sky-300">production blocks</span> (what live rules
            stopped) with <span className="text-amber-300">shadow blocks</span> (what this hypothesis
            would have stopped). Gaps highlight a new attack wave current rules missed.
          </p>
        </div>
        {shadowOnlyTotal > 0 ? (
          <p
            className="text-right text-xs font-bold uppercase tracking-wide text-amber-200"
            data-testid="backtest-shadow-only-total"
          >
            {shadowOnlyTotal} shadow-only blocks
          </p>
        ) : null}
      </div>

      <div
        className="w-full min-h-[240px] rounded-xl border border-slate-700/90 bg-slate-950/60 p-2"
        style={{ height }}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 12, right: 12, left: 4, bottom: 4 }}>
            <defs>
              <linearGradient id="prodBlocksFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.45} />
                <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id="shadowBlocksFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#fbbf24" stopOpacity={0.5} />
                <stop offset="95%" stopColor="#fbbf24" stopOpacity={0.06} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis
              dataKey="label"
              stroke="#64748b"
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              interval="preserveStartEnd"
              minTickGap={28}
            />
            <YAxis
              allowDecimals={false}
              stroke="#64748b"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              width={36}
              label={{
                value: "Blocks",
                angle: -90,
                position: "insideLeft",
                fill: "#64748b",
                fontSize: 10,
              }}
            />
            <Tooltip content={<ChartTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
              formatter={(value) => <span className="text-slate-300">{value}</span>}
            />
            <Area
              type="monotone"
              dataKey="production_blocks"
              name="Production blocks"
              stroke="#38bdf8"
              strokeWidth={2.5}
              fill="url(#prodBlocksFill)"
              dot={{ r: 2, fill: "#0ea5e9" }}
              activeDot={{ r: 5 }}
            />
            <Area
              type="monotone"
              dataKey="shadow_blocks"
              name="Shadow blocks"
              stroke="#fbbf24"
              strokeWidth={2.5}
              fill="url(#shadowBlocksFill)"
              dot={{ r: 2, fill: "#f59e0b" }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="shadow_only_blocks"
              name="Shadow-only (missed by prod)"
              stroke="#f472b6"
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={{ r: 2, fill: "#ec4899" }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
