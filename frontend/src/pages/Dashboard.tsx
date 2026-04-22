import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
} from "recharts";
import {
  analytics,
  type AnalyticsSummary,
  type HourlyStat,
  type TopEntity,
  type AuditEntry,
} from "../api/client";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

const DECISION_COLORS = {
  allow: "#22c55e",
  review: "#f59e0b",
  deny: "#ef4444",
};

function rowToAuditEntry(r: unknown): AuditEntry | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Record<string, unknown>;
  if (typeof o.entity_id !== "string" || typeof o.decision !== "string") return null;
  return {
    trace_id: String(o.trace_id ?? ""),
    entity_id: o.entity_id,
    tenant_id: String(o.tenant_id ?? ""),
    event_type: String(o.event_type ?? ""),
    decision: o.decision,
    score: Number(o.score ?? 0),
    tags: Array.isArray(o.tags) ? o.tags.map(String) : [],
    rule_hits: Array.isArray(o.rule_hits) ? o.rule_hits.map(String) : [],
    created_at: String(o.created_at ?? new Date().toISOString()),
  };
}

function summarizeFromRows(rows: unknown[]): AnalyticsSummary {
  const entries = rows.map(rowToAuditEntry).filter((e): e is AuditEntry => e != null);
  const n = entries.length;
  if (n === 0) {
    return { total_decisions: 0, deny_rate: 0, review_rate: 0, avg_score: 0 };
  }
  let deny = 0;
  let review = 0;
  let scoreSum = 0;
  for (const e of entries) {
    if (e.decision === "deny") deny += 1;
    else if (e.decision === "review") review += 1;
    scoreSum += e.score;
  }
  return {
    total_decisions: n,
    deny_rate: deny / n,
    review_rate: review / n,
    avg_score: scoreSum / n,
  };
}

export default function Dashboard() {
  const { tenantId } = useTenantEnvironment();
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [hourly, setHourly] = useState<HourlyStat[]>([]);
  const [topEntities, setTopEntities] = useState<TopEntity[]>([]);
  const [recentDecisions, setRecentDecisions] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dataWarnings, setDataWarnings] = useState<string[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const firstLoadRef = useRef(true);

  const fetchData = useCallback(async () => {
    const isFirst = firstLoadRef.current;
    if (isFirst) setLoading(true);
    else setRefreshing(true);
    try {
      const [sResp, hResp, tResp] = await Promise.allSettled([
        analytics.decisions({ tenant_id: tenantId, limit: 500 }),
        analytics.hourly({ tenant_id: tenantId, days: 24 }),
        analytics.topEntities({ tenant_id: tenantId, limit: 10 }),
      ]);
      const warnings: string[] = [];

      if (hResp.status === "fulfilled") setHourly(hResp.value.rows ?? []);
      else {
        setHourly([]);
        warnings.push("Hourly trend data unavailable");
      }

      if (tResp.status === "fulfilled") setTopEntities(tResp.value.entities ?? []);
      else {
        setTopEntities([]);
        warnings.push("Top entities data unavailable");
      }

      if (sResp.status === "fulfilled") {
        const rows = sResp.value.rows ?? [];
        setSummary(summarizeFromRows(rows));
        const parsed = rows.map(rowToAuditEntry).filter((e): e is AuditEntry => e != null);
        parsed.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        setRecentDecisions(parsed.slice(0, 20));
      } else {
        setSummary({ total_decisions: 0, deny_rate: 0, review_rate: 0, avg_score: 0 });
        setRecentDecisions([]);
        warnings.push("Decision audit rows unavailable");
      }
      setDataWarnings(warnings);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Dashboard", action: "load dashboard metrics" }));
    } finally {
      setLoading(false);
      setRefreshing(false);
      firstLoadRef.current = false;
    }
  }, [tenantId]);

  useEffect(() => {
    setSummary(null);
    setHourly([]);
    setTopEntities([]);
    setRecentDecisions([]);
    setDataWarnings([]);
    firstLoadRef.current = true;
    setLoading(true);
  }, [tenantId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void fetchData();
    }, 30_000);
    const onVis = () => {
      if (document.visibilityState === "visible") void fetchData();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [autoRefresh, fetchData]);

  const aggregatedHourly = useMemo(() => {
    const map = new Map<string, { hour: string; allow: number; review: number; deny: number }>();
    for (const row of hourly) {
      let entry = map.get(row.hour);
      if (!entry) {
        entry = { hour: row.hour, allow: 0, review: 0, deny: 0 };
        map.set(row.hour, entry);
      }
      if (row.decision === "allow") entry.allow += row.event_count;
      else if (row.decision === "review") entry.review += row.event_count;
      else if (row.decision === "deny") entry.deny += row.event_count;
    }
    return Array.from(map.values()).sort((a, b) => a.hour.localeCompare(b.hour));
  }, [hourly]);

  const pieData = aggregatedHourly.length
    ? [
        { name: "Allow", value: aggregatedHourly.reduce((s, h) => s + h.allow, 0) },
        { name: "Review", value: aggregatedHourly.reduce((s, h) => s + h.review, 0) },
        { name: "Deny", value: aggregatedHourly.reduce((s, h) => s + h.deny, 0) },
      ].filter((d) => d.value > 0)
    : [];

  const hasChartData = aggregatedHourly.some((h) => h.allow + h.review + h.deny > 0);
  const showEmptyHonest = summary && summary.total_decisions === 0 && !hasChartData;

  if (loading && summary === null && hourly.length === 0) return <LoadingState />;
  if (error) return <ErrorState message={error} onRetry={() => void fetchData()} />;

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <PageTitle module="dashboard">Dashboard</PageTitle>
        <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
          <span className="text-gray-600">Tenant: {tenantId}</span>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              className="rounded border-surface-600"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh (30s, when tab visible)
          </label>
          <button
            type="button"
            disabled={refreshing}
            onClick={() => void fetchData()}
            className="px-3 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 text-gray-200 disabled:opacity-50"
          >
            {refreshing ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
      </div>

      {showEmptyHonest && (
        <p className="text-sm text-gray-500 border border-surface-700 rounded-lg px-4 py-3 bg-surface-900/60">
          No decision rows returned for this tenant in the analytics window. KPIs below are zero until events are ingested.
        </p>
      )}
      {dataWarnings.length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200/90">
          <p className="font-medium">Some dashboard panels are degraded.</p>
          <p className="text-amber-100/80">{dataWarnings.join(" · ")}</p>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          title="Decisions (sample)"
          value={summary?.total_decisions?.toLocaleString() ?? "—"}
          accent="text-brand-400"
        />
        <KPICard
          title="Deny Rate"
          value={summary ? `${(summary.deny_rate * 100).toFixed(1)}%` : "—"}
          accent="text-risk-critical"
        />
        <KPICard
          title="Review Rate"
          value={summary ? `${(summary.review_rate * 100).toFixed(1)}%` : "—"}
          accent="text-risk-medium"
        />
        <KPICard
          title="Avg Score"
          value={summary ? summary.avg_score.toFixed(1) : "—"}
          accent="text-risk-high"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Hourly Line Chart */}
        <div className="lg:col-span-2 bg-surface-900 border border-surface-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">
            Decisions Over Time
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={aggregatedHourly}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2233" />
              <XAxis
                dataKey="hour"
                stroke="#6b7280"
                tick={{ fontSize: 11 }}
                tickFormatter={(v: string) => {
                  const d = new Date(v);
                  return `${d.getHours().toString().padStart(2, "0")}:00`;
                }}
              />
              <YAxis stroke="#6b7280" tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#161923",
                  border: "1px solid #2a2f44",
                  borderRadius: 8,
                  color: "#e5e7eb",
                }}
              />
              <Line
                type="monotone"
                dataKey="allow"
                stroke={DECISION_COLORS.allow}
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="review"
                stroke={DECISION_COLORS.review}
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="deny"
                stroke={DECISION_COLORS.deny}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
          <div className="flex gap-4 mt-2 justify-center">
            <Legend color={DECISION_COLORS.allow} label="Allow" />
            <Legend color={DECISION_COLORS.review} label="Review" />
            <Legend color={DECISION_COLORS.deny} label="Deny" />
          </div>
        </div>

        {/* Pie Chart */}
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">
            Decision Distribution
          </h2>
          {pieData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {pieData.map((d) => (
                      <Cell
                        key={d.name}
                        fill={DECISION_COLORS[d.name === "Allow" ? "allow" : d.name === "Review" ? "review" : "deny"]}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#161923",
                      border: "1px solid #2a2f44",
                      borderRadius: 8,
                      color: "#e5e7eb",
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex gap-4 mt-2 justify-center">
                <Legend color={DECISION_COLORS.allow} label="Allow" />
                <Legend color={DECISION_COLORS.review} label="Review" />
                <Legend color={DECISION_COLORS.deny} label="Deny" />
              </div>
            </>
          ) : (
            <div className="h-[280px] flex items-center justify-center text-sm text-gray-500">
              No hourly decision mix for this range
            </div>
          )}
        </div>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Entities Bar Chart */}
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">
            Top Risky Entities
          </h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={topEntities}
              layout="vertical"
              margin={{ left: 20 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2233" />
              <XAxis type="number" stroke="#6b7280" tick={{ fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="entity_id"
                stroke="#6b7280"
                tick={{ fontSize: 11 }}
                width={120}
                tickFormatter={(v: string) =>
                  v.length > 16 ? v.slice(0, 16) + "\u2026" : v
                }
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#161923",
                  border: "1px solid #2a2f44",
                  borderRadius: 8,
                  color: "#e5e7eb",
                }}
              />
              <Bar dataKey="avg_score" fill="#f97316" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Recent Decisions Table */}
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">
            Recent Decisions
          </h2>
          <div className="overflow-auto max-h-[340px]">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 border-b border-surface-700">
                  <th className="text-left py-2 px-2 font-medium">Entity</th>
                  <th className="text-left py-2 px-2 font-medium">Decision</th>
                  <th className="text-right py-2 px-2 font-medium">Score</th>
                  <th className="text-right py-2 px-2 font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {recentDecisions.map((d, i) => (
                  <tr
                    key={d.trace_id ?? i}
                    className="border-b border-surface-800 hover:bg-surface-800/50"
                  >
                    <td className="py-2 px-2 text-gray-300 font-mono text-xs">
                      {d.entity_id.length > 20
                        ? d.entity_id.slice(0, 20) + "\u2026"
                        : d.entity_id}
                    </td>
                    <td className="py-2 px-2">
                      <DecisionBadge decision={d.decision} />
                    </td>
                    <td className="py-2 px-2 text-right text-gray-300">
                      {d.score}
                    </td>
                    <td className="py-2 px-2 text-right text-gray-500 text-xs">
                      {new Date(d.created_at).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
                {recentDecisions.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-8 text-center text-gray-500">
                      No recent decisions
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function KPICard({
  title,
  value,
  accent,
}: {
  title: string;
  value: string;
  accent: string;
}) {
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
      <div className="text-xs text-gray-400 font-medium mb-1">{title}</div>
      <div className={`text-2xl font-bold ${accent}`}>{value}</div>
    </div>
  );
}

function DecisionBadge({ decision }: { decision: string }) {
  const styles: Record<string, string> = {
    allow: "bg-green-500/20 text-green-400",
    review: "bg-amber-500/20 text-amber-400",
    deny: "bg-red-500/20 text-red-400",
  };
  return (
    <span
      className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold capitalize ${styles[decision] ?? "bg-gray-500/20 text-gray-400"}`}
    >
      {decision}
    </span>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-gray-400">
      <span
        className="w-2.5 h-2.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <div className="w-10 h-10 border-2 border-brand-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-gray-400 text-sm">Loading dashboard...</p>
      </div>
    </div>
  );
}

function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center space-y-3">
        <div className="text-red-400 text-4xl">!</div>
        <p className="text-gray-300 font-medium">Failed to load dashboard</p>
        <p className="text-gray-500 text-sm max-w-sm">{message}</p>
        <SupportIdHint
          message={message}
          className="flex flex-wrap items-center justify-center gap-2 text-[11px] text-red-300/85"
          buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
        />
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition-colors"
        >
          Retry
        </button>
      </div>
    </div>
  );
}
