import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { integrations, type PromoAbuseResponse, type PromoAbuseUserRow } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const DEFAULT_COUPON = "NEWUSER50";

function riskTone(risk: string): string {
  if (risk === "critical") return "border-rose-500/45 text-rose-200 bg-rose-950/25";
  if (risk === "elevated") return "border-amber-500/45 text-amber-200 bg-amber-950/25";
  return "border-emerald-500/40 text-emerald-200 bg-emerald-950/20";
}

export default function PromoAbuseDashboard(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [couponCode, setCouponCode] = useState(DEFAULT_COUPON);
  const [data, setData] = useState<PromoAbuseResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useRegisterPageMeta({ title: "Promo abuse", subtitle: "Coupon concentration" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrations.promoAbuse({
        tenant_id: tenantId,
        coupon_code: couponCode.trim() || DEFAULT_COUPON,
      });
      setData(res);
      setError(null);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Promo abuse", action: "load coupon usage" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId, couponCode]);

  useEffect(() => {
    void load();
  }, [load]);

  const chartData = useMemo(
    () =>
      (data?.daily_series ?? []).map((d) => ({
        date: d.date.slice(5),
        unique_users: d.unique_users,
        redemptions: d.redemptions,
      })),
    [data],
  );

  const topUsers = useMemo(() => (data?.users ?? []).slice(0, 25), [data]);

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="analytics">Promo abuse</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Track how many <strong className="text-gray-300">unique users</strong> redeem a single coupon code.
            Spikes on codes like <span className="font-mono text-brand-300">NEWUSER50</span> often indicate referral
            farming, multi-account abuse, or leaked influencer codes.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">GET /api/ingress/v1/analytics/promo-abuse</p>
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

      <form
        className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 flex flex-wrap gap-3 items-end"
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <label className="text-xs text-gray-500 block min-w-[200px]">
          Coupon code
          <input
            value={couponCode}
            onChange={(e) => setCouponCode(e.target.value.toUpperCase())}
            placeholder="NEWUSER50"
            className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-3 py-2 text-sm font-mono text-gray-100 uppercase"
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white"
        >
          Analyze
        </button>
      </form>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-16 text-center">Loading promo usage…</p>
      ) : data ? (
        <>
          <div
            className={`rounded-2xl border px-6 py-5 flex flex-wrap items-center justify-between gap-6 ${riskTone(
              data.summary.abuse_risk,
            )}`}
          >
            <div>
              <p className="text-[11px] uppercase tracking-wide opacity-80">Unique users · {data.coupon_code}</p>
              <p className="text-5xl font-bold tabular-nums mt-1">{data.summary.unique_users}</p>
              <p className="text-xs mt-2 opacity-90">
                {data.summary.total_redemptions} total redemptions · {data.window_days}d window · tenant{" "}
                <span className="font-mono">{data.tenant_id}</span>
              </p>
            </div>
            <div className="text-right text-xs space-y-1 opacity-90">
              <p>
                Warn ≥ {data.thresholds.warn_unique_users} users · Critical ≥{" "}
                {data.thresholds.critical_unique_users}
              </p>
              <p>{data.summary.distinct_devices} distinct devices</p>
              <p className="capitalize">Risk: {data.summary.abuse_risk}</p>
            </div>
          </div>

          {data.signals.length > 0 ? (
            <ul className="rounded-xl border border-amber-500/30 bg-amber-950/15 px-4 py-3 text-sm text-amber-100/90 space-y-1 list-disc pl-5">
              {data.signals.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          ) : null}

          <section className="rounded-xl border border-surface-700 bg-surface-900/50 p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-4">
              Daily unique redeemers
            </h2>
            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a3048" />
                  <XAxis dataKey="date" tick={{ fill: "#9ca3af", fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fill: "#9ca3af", fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      background: "#111827",
                      border: "1px solid #374151",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="unique_users" name="Unique users" fill="#6366f1" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="rounded-xl border border-surface-700 overflow-hidden">
            <div className="px-4 py-3 border-b border-surface-700">
              <h2 className="text-sm font-semibold text-gray-200">Redeeming users</h2>
              <p className="text-[11px] text-gray-500 mt-0.5">Top {topUsers.length} by redemption count</p>
            </div>
            <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface-900 text-gray-500 uppercase tracking-wide">
                  <tr className="border-b border-surface-700">
                    <th className="text-left px-3 py-2">User</th>
                    <th className="text-right px-3 py-2">Redemptions</th>
                    <th className="text-left px-3 py-2">Device</th>
                    <th className="text-left px-3 py-2">Last seen</th>
                    <th className="text-left px-3 py-2">Flags</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-800 text-gray-300">
                  {topUsers.map((row) => (
                    <UserRow key={row.user_id} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function UserRow({ row }: { row: PromoAbuseUserRow }): ReactElement {
  return (
    <tr>
      <td className="px-3 py-2">
        <p className="font-mono text-gray-200">{row.user_id}</p>
        <p className="text-[10px] text-gray-600">{row.display_name}</p>
      </td>
      <td className="px-3 py-2 text-right tabular-nums font-semibold">{row.redemption_count}</td>
      <td className="px-3 py-2 font-mono text-gray-500">{row.device_id}</td>
      <td className="px-3 py-2 font-mono text-gray-500 whitespace-nowrap">
        {row.last_redeemed_at ? new Date(row.last_redeemed_at).toLocaleString() : "—"}
      </td>
      <td className="px-3 py-2">
        {row.flags?.length ? (
          <div className="flex flex-wrap gap-1">
            {row.flags.map((f) => (
              <span
                key={f}
                className="text-[9px] uppercase px-1.5 py-0.5 rounded border border-amber-500/35 text-amber-200/90"
              >
                {f.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-gray-600">—</span>
        )}
      </td>
    </tr>
  );
}
