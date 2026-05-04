import { useEffect, useState } from "react";
import { PageTitle } from "../components/PageTitle";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

/**
 * Embedded KPI dashboards (decision-api /v1/analytics/dashboards/kpis).
 */
export default function ExecutiveDashboards() {
  const [tenantId, setTenantId] = useState("demo-tenant");
  const [kpis, setKpis] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const base = (import.meta.env.VITE_DECISION_API_URL as string | undefined)?.replace(/\/$/, "") || "";
    const key = (import.meta.env.VITE_API_KEY as string) || "";
    void fetch(`${base}/v1/analytics/dashboards/kpis?tenant_id=${encodeURIComponent(tenantId)}`, {
      headers: { "X-Api-Key": key },
    })
      .then((r) => r.json())
      .then(setKpis)
      .catch(() => setKpis({ error: "fetch_failed" }));
  }, [tenantId]);

  const chartData = [
    { name: "approvals", value: typeof kpis?.approval_rate_pct === "number" ? (kpis.approval_rate_pct as number) : 0 },
    { name: "fraud", value: typeof kpis?.fraud_rate_pct === "number" ? (kpis.fraud_rate_pct as number) : 0 },
  ];

  return (
    <div className="p-6 space-y-4">
      <PageTitle module="dashboard">
        Executive dashboards
        <span className="block text-xs font-normal text-gray-500 mt-1">Redis-cached KPIs (wire ClickHouse for live metrics)</span>
      </PageTitle>
      <div className="flex gap-2 items-center text-sm">
        <label className="text-gray-400">Tenant</label>
        <input
          className="bg-surface-800 border border-surface-600 rounded px-2 py-1"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
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
      {kpis && (
        <pre className="text-xs bg-black/40 border border-surface-700 rounded p-3 overflow-auto text-gray-300">
          {JSON.stringify(kpis, null, 2)}
        </pre>
      )}
    </div>
  );
}
