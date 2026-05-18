import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  integrations,
  type SellerIntegrityResponse,
  type SellerIntegrityRow,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

function tierTone(tier: string): string {
  if (tier === "critical") return "border-rose-500/45 text-rose-200 bg-rose-950/25";
  if (tier === "warning") return "border-amber-500/45 text-amber-200 bg-amber-950/25";
  if (tier === "trusted") return "border-emerald-500/40 text-emerald-200 bg-emerald-950/20";
  return "border-surface-600 text-gray-300 bg-surface-900/60";
}

function ratioBarColor(ratio: number, warn: number, critical: number): string {
  if (ratio >= critical) return "#f43f5e";
  if (ratio >= warn) return "#f59e0b";
  return "#6366f1";
}

export default function SellerIntegrityDashboard(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<SellerIntegrityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tierFilter, setTierFilter] = useState<"all" | "at_risk">("at_risk");

  useRegisterPageMeta({ title: "Seller integrity", subtitle: "Reviews vs deliveries" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrations.sellerIntegrity({ tenant_id: tenantId, window_days: 30, limit: 40 });
      setData(res);
      setError(null);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Seller integrity", action: "load scores" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = useMemo(() => {
    const all = data?.sellers ?? [];
    if (tierFilter === "all") return all;
    return all.filter((s) => s.integrity_tier === "warning" || s.integrity_tier === "critical");
  }, [data, tierFilter]);

  const chartData = useMemo(
    () =>
      [...(data?.sellers ?? [])]
        .filter((s) => s.successful_deliveries > 0)
        .sort((a, b) => b.review_to_delivery_ratio - a.review_to_delivery_ratio)
        .slice(0, 12)
        .map((s) => ({
          name: s.store_slug.slice(0, 10),
          ratio: s.review_to_delivery_ratio,
          deliveries: s.successful_deliveries,
          reviews: s.review_count,
        })),
    [data],
  );

  const warn = data?.thresholds.warn_ratio_above ?? 0.85;
  const critical = data?.thresholds.critical_ratio_above ?? 1.05;

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="integrations">Seller integrity</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Marketplace seller trust scores from the ratio of <strong className="text-gray-300">reviews</strong> to{" "}
            <strong className="text-gray-300">successful deliveries</strong>. Inflated review volume without matching
            fulfillment is a common fake-store and review-farm signal.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET /api/ingress/v1/marketplace/seller-integrity
          </p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => void load()}
          className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700 disabled:opacity-50"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-16 text-center">Computing seller integrity…</p>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Sellers" value={data.summary.seller_count} />
            <StatCard label="At risk" value={data.summary.at_risk_sellers} accent="amber" />
            <StatCard label="Avg integrity" value={data.summary.avg_integrity_score} />
            <StatCard
              label="Median review ÷ delivery"
              value={data.summary.median_review_to_delivery_ratio}
              decimal
            />
          </div>

          {data.signals.length > 0 ? (
            <ul className="rounded-xl border border-amber-500/30 bg-amber-950/15 px-4 py-3 text-sm text-amber-100/90 space-y-1 list-disc pl-5">
              {data.signals.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          ) : null}

          <section className="rounded-xl border border-surface-700 bg-surface-900/50 p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">
              Review-to-delivery ratio (top 12 by ratio)
            </h2>
            <p className="text-[11px] text-gray-600 mb-4">
              Healthy band {data.thresholds.healthy_ratio_min}–{data.thresholds.healthy_ratio_max} · warn ≥
              {warn} · critical ≥ {critical}
            </p>
            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a3048" />
                  <XAxis dataKey="name" tick={{ fill: "#9ca3af", fontSize: 10 }} />
                  <YAxis tick={{ fill: "#9ca3af", fontSize: 11 }} domain={[0, "auto"]} />
                  <Tooltip
                    contentStyle={{
                      background: "#111827",
                      border: "1px solid #374151",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    formatter={(value, name) => {
                      const n = typeof value === "number" ? value : Number(value);
                      if (name === "ratio") return [Number.isFinite(n) ? n.toFixed(3) : "—", "Review ÷ delivery"];
                      return [value ?? "—", name];
                    }}
                  />
                  <ReferenceLine y={warn} stroke="#f59e0b" strokeDasharray="4 4" />
                  <ReferenceLine y={critical} stroke="#f43f5e" strokeDasharray="4 4" />
                  <Bar dataKey="ratio" name="ratio" radius={[4, 4, 0, 0]}>
                    {chartData.map((entry) => (
                      <Cell key={entry.name} fill={ratioBarColor(entry.ratio, warn, critical)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <div className="flex flex-wrap items-center gap-3 text-xs">
            <label className="text-gray-500">
              Show
              <select
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value as "all" | "at_risk")}
                className="ml-2 rounded-md border border-surface-600 bg-surface-900 px-2 py-1 text-gray-200"
              >
                <option value="at_risk">At-risk only</option>
                <option value="all">All sellers</option>
              </select>
            </label>
            <span className="text-gray-600">
              {data.window_days}d window · {data.summary.total_deliveries.toLocaleString()} deliveries ·{" "}
              {data.summary.total_reviews.toLocaleString()} reviews
            </span>
          </div>

          <section className="rounded-xl border border-surface-700 overflow-hidden">
            <div className="px-4 py-3 border-b border-surface-700 flex justify-between items-center">
              <h2 className="text-sm font-semibold text-gray-200">Seller scores</h2>
              <span className="text-[11px] text-gray-500">{rows.length} rows</span>
            </div>
            <div className="overflow-x-auto max-h-[480px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface-900 text-gray-500 uppercase tracking-wide">
                  <tr className="border-b border-surface-700">
                    <th className="text-left px-3 py-2">Seller</th>
                    <th className="text-right px-3 py-2">Deliveries</th>
                    <th className="text-right px-3 py-2">Reviews</th>
                    <th className="text-right px-3 py-2">Ratio</th>
                    <th className="text-right px-3 py-2">Integrity</th>
                    <th className="text-left px-3 py-2">Tier</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-800 text-gray-300">
                  {rows.map((row) => (
                    <SellerRow key={row.seller_id} row={row} warn={warn} critical={critical} />
                  ))}
                </tbody>
              </table>
              {rows.length === 0 ? (
                <p className="text-sm text-gray-500 py-12 text-center">No sellers match this filter.</p>
              ) : null}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
  decimal,
}: {
  label: string;
  value: number;
  accent?: string;
  decimal?: boolean;
}): ReactElement {
  const tone =
    accent === "amber"
      ? "border-amber-500/35 bg-amber-950/20"
      : "border-surface-700 bg-surface-900/50";
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone}`}>
      <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className="text-2xl font-bold tabular-nums text-gray-100 mt-1">
        {decimal ? value.toFixed(2) : value}
      </p>
    </div>
  );
}

function SellerRow({
  row,
  warn,
  critical,
}: {
  row: SellerIntegrityRow;
  warn: number;
  critical: number;
}): ReactElement {
  return (
    <tr className="hover:bg-surface-900/40">
      <td className="px-3 py-2">
        <p className="font-mono text-gray-200">{row.seller_id}</p>
        <p className="text-[10px] text-gray-600">
          {row.display_name} · {row.store_slug} · {row.category}
        </p>
        {row.signals.length > 0 ? (
          <p className="text-[9px] text-amber-300/90 mt-0.5">{row.signals.join(" · ")}</p>
        ) : null}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{row.successful_deliveries}</td>
      <td className="px-3 py-2 text-right tabular-nums">{row.review_count}</td>
      <td
        className={`px-3 py-2 text-right tabular-nums font-semibold ${
          row.review_to_delivery_ratio >= critical
            ? "text-rose-300"
            : row.review_to_delivery_ratio >= warn
              ? "text-amber-300"
              : "text-gray-200"
        }`}
      >
        {row.review_to_delivery_ratio.toFixed(3)}
      </td>
      <td className="px-3 py-2 text-right">
        <div className="inline-flex flex-col items-end gap-1 min-w-[72px]">
          <span className="font-bold tabular-nums">{row.integrity_score}</span>
          <div className="w-full h-1.5 rounded-full bg-surface-800 overflow-hidden">
            <div
              className={`h-full rounded-full ${
                row.integrity_score < 40
                  ? "bg-rose-500"
                  : row.integrity_score < 70
                    ? "bg-amber-500"
                    : "bg-emerald-500"
              }`}
              style={{ width: `${row.integrity_score}%` }}
            />
          </div>
        </div>
      </td>
      <td className="px-3 py-2">
        <span
          className={`text-[9px] uppercase px-1.5 py-0.5 rounded border font-semibold ${tierTone(row.integrity_tier)}`}
        >
          {row.integrity_tier}
        </span>
      </td>
    </tr>
  );
}
