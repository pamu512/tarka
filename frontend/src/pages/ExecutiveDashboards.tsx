import { useEffect, useMemo, useState } from "react";
import { PageTitle } from "../components/PageTitle";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

function calendarDateInTimeZone(d: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(d);
  const y = parts.find((p) => p.type === "year")?.value;
  const m = parts.find((p) => p.type === "month")?.value;
  const day = parts.find((p) => p.type === "day")?.value;
  return `${y}-${m}-${day}`;
}

/**
 * Executive OLAP summary (decision-api ``/v1/analytics/dashboards/summary``): volume, block rate, top rules, geo spikes.
 */
export default function ExecutiveDashboards() {
  const [tenantId, setTenantId] = useState("demo-tenant");
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", []);
  const [periodStart, setPeriodStart] = useState(() => {
    const end = new Date();
    const start = new Date(end.getTime() - 6 * 86400000);
    return calendarDateInTimeZone(start, timeZone);
  });
  const [periodEnd, setPeriodEnd] = useState(() => calendarDateInTimeZone(new Date(), timeZone));

  useEffect(() => {
    const base = (import.meta.env.VITE_DECISION_API_URL as string | undefined)?.replace(/\/$/, "") || "";
    const key = (import.meta.env.VITE_API_KEY as string) || "";
    const q = new URLSearchParams({
      tenant_id: tenantId,
      period_start: periodStart,
      period_end: periodEnd,
      timezone: timeZone,
    });
    void fetch(`${base}/v1/analytics/dashboards/summary?${q.toString()}`, {
      headers: { "X-Api-Key": key },
    })
      .then((r) => r.json())
      .then(setSummary)
      .catch(() => setSummary({ error: "fetch_failed" }));
  }, [tenantId, periodStart, periodEnd, timeZone]);

  const chartData = [
    {
      name: "approvals",
      value: typeof summary?.approval_rate_pct === "number" ? (summary.approval_rate_pct as number) : 0,
    },
    {
      name: "fraud",
      value: typeof summary?.fraud_rate_pct === "number" ? (summary.fraud_rate_pct as number) : 0,
    },
  ];

  return (
    <div className="p-6 space-y-4">
      <PageTitle module="dashboard">
        Executive dashboards
        <span className="block text-xs font-normal text-gray-500 mt-1">
          OLAP-backed metrics (cached); window uses IANA timezone {timeZone}
        </span>
      </PageTitle>
      <div className="flex flex-wrap gap-3 items-center text-sm">
        <label className="text-gray-400">Tenant</label>
        <input
          className="bg-surface-800 border border-surface-600 rounded px-2 py-1"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
        />
        <label className="text-gray-400">From</label>
        <input
          type="date"
          className="bg-surface-800 border border-surface-600 rounded px-2 py-1"
          value={periodStart}
          onChange={(e) => setPeriodStart(e.target.value)}
        />
        <label className="text-gray-400">To</label>
        <input
          type="date"
          className="bg-surface-800 border border-surface-600 rounded px-2 py-1"
          value={periodEnd}
          onChange={(e) => setPeriodEnd(e.target.value)}
        />
      </div>
      <div className="h-64 border border-surface-700 rounded-lg bg-surface-900/40 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData}>
            <XAxis dataKey="name" stroke="#9ca3af" />
            <YAxis stroke="#9ca3af" />
            <Tooltip contentStyle={{ background: "#111827", border: "1px solid #374151" }} />
            <Bar dataKey="value" fill="#38bdf8" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {summary && (
        <pre className="text-xs bg-black/40 border border-surface-700 rounded p-3 overflow-auto text-gray-300">
          {JSON.stringify(summary, null, 2)}
        </pre>
      )}
    </div>
  );
}
