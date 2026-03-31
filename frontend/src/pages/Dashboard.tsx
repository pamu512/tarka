import { useEffect, useState, useCallback, useMemo } from "react";
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
  decisions,
  type AnalyticsSummary,
  type HourlyStat,
  type TopEntity,
  type AuditEntry,
} from "../api/client";

const DECISION_COLORS = {
  allow: "#22c55e",
  review: "#f59e0b",
  deny: "#ef4444",
};

export default function Dashboard() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [hourly, setHourly] = useState<HourlyStat[]>([]);
  const [topEntities, setTopEntities] = useState<TopEntity[]>([]);
  const [recentDecisions, setRecentDecisions] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [sResp, hResp, tResp] = await Promise.allSettled([
        analytics.decisions({ limit: 1 }),
        analytics.hourly({ days: 24 }),
        analytics.topEntities({ limit: 10 }),
      ]);
      if (hResp.status === "fulfilled") setHourly(hResp.value.rows);
      if (tResp.status === "fulfilled") setTopEntities(tResp.value.entities);
      if (sResp.status === "fulfilled") {
        const rows = sResp.value.rows;
        const total = rows.length;
        setSummary({
          total_decisions: total,
          deny_rate: 0,
          review_rate: 0,
          avg_score: 0,
        });
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

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
      ]
    : [];

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} onRetry={fetchData} />;

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Dashboard</h1>
        <span className="text-xs text-gray-500">Auto-refreshes every 30s</span>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          title="Total Decisions (24h)"
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
                <Cell fill={DECISION_COLORS.allow} />
                <Cell fill={DECISION_COLORS.review} />
                <Cell fill={DECISION_COLORS.deny} />
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
