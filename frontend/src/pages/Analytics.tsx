import { useEffect, useState, useCallback, useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from "recharts";
import {
  analytics,
  ml,
  type AnalyticsDecisionScorecard,
  type HourlyStat,
  type ModelInfo,
  type TopEntity,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useToast } from "../context/ToastContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const HOURS_OPTIONS = [6, 12, 24, 48, 72];

function buildScorecardExportBundle(data: AnalyticsDecisionScorecard) {
  return {
    schema: "tarka_decision_scorecard_export_v1",
    exported_at: new Date().toISOString(),
    source_path: "GET /v1/analytics/scorecard",
    service: "analytics-sink",
    data,
  };
}

function buildScorecardDiscussionMarkdown(data: AnalyticsDecisionScorecard): string {
  const lines: string[] = [
    `## Decision scorecard — \`${data.tenant_id}\``,
    "",
    `**Window:** ${data.window_days} day(s) · **Total events:** ${data.total_events.toLocaleString()} · **Deny rate:** ${data.deny_rate_pct.toFixed(2)}%`,
    "",
    "### Per decision",
    "",
    "| Decision | Count | % | Avg score |",
    "| --- | ---: | ---: | ---: |",
  ];
  for (const r of data.per_decision) {
    lines.push(`| ${r.decision} | ${r.event_count} | ${r.event_pct} | ${r.avg_score.toFixed(1)} |`);
  }
  lines.push("", "### Top rule hits", "");
  if (data.top_rule_hits.length === 0) {
    lines.push("_No rule hits in window._");
  } else {
    lines.push("| Rule | Hits |", "| --- | ---: |");
    for (const raw of data.top_rule_hits) {
      const rid = String(raw.rule_id ?? "");
      const hits = raw.hit_count ?? raw["hit_count"];
      lines.push(`| \`${rid || "—"}\` | ${typeof hits === "number" ? hits : String(hits ?? "—")} |`);
    }
  }
  lines.push("", "---", `_Exported from Tarka Analytics · ${new Date().toISOString()}_`);
  return lines.join("\n");
}

export default function Analytics() {
  const [hours, setHours] = useState(24);
  const [hourlyData, setHourlyData] = useState<HourlyStat[]>([]);
  const [topEntities, setTopEntities] = useState<TopEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [governanceBusy, setGovernanceBusy] = useState(false);
  const [governanceMessage, setGovernanceMessage] = useState<string>("");
  const [scorecard, setScorecard] = useState<AnalyticsDecisionScorecard | null>(null);
  const { toast } = useToast();

  const copyScorecardText = useCallback(
    async (text: string, okMessage: string) => {
      try {
        await navigator.clipboard.writeText(text);
        toast(okMessage, "success");
      } catch {
        toast("Clipboard unavailable", "error");
      }
    },
    [toast],
  );

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [hourlyRes, topRes, scoreRes] = await Promise.allSettled([
        analytics.hourly({ days: hours }),
        analytics.topEntities({ limit: 20, days: hours }),
        analytics.scorecard({ days: hours }),
      ]);
      if (hourlyRes.status !== "fulfilled") throw hourlyRes.reason;
      if (topRes.status !== "fulfilled") throw topRes.reason;
      setHourlyData(hourlyRes.value.rows);
      setTopEntities(topRes.value.entities);
      setScorecard(scoreRes.status === "fulfilled" ? scoreRes.value : null);
      const m = await ml.models();
      setModels(m.models);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Analytics", action: "load analytics" }));
      setScorecard(null);
    } finally {
      setLoading(false);
    }
  }, [hours]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const aggregatedHourly = useMemo(() => {
    const map = new Map<string, { hour: string; allow: number; review: number; deny: number; total: number }>();
    for (const row of hourlyData) {
      let entry = map.get(row.hour);
      if (!entry) {
        entry = { hour: row.hour, allow: 0, review: 0, deny: 0, total: 0 };
        map.set(row.hour, entry);
      }
      entry.total += row.event_count;
      if (row.decision === "allow") entry.allow += row.event_count;
      else if (row.decision === "review") entry.review += row.event_count;
      else if (row.decision === "deny") entry.deny += row.event_count;
    }
    return Array.from(map.values()).sort((a, b) => a.hour.localeCompare(b.hour));
  }, [hourlyData]);

  const totalVolume = aggregatedHourly.reduce((s, h) => s + h.total, 0);

  const groupedModels = useMemo(() => {
    const map = new Map<string, ModelInfo[]>();
    for (const m of models) {
      const arr = map.get(m.model_name) || [];
      arr.push(m);
      map.set(m.model_name, arr);
    }
    for (const [, arr] of map) {
      arr.sort((a, b) => a.version - b.version);
    }
    return Array.from(map.entries());
  }, [models]);

  const runGovernance = async (fn: () => Promise<unknown>, success: string) => {
    setGovernanceBusy(true);
    setGovernanceMessage("");
    try {
      await fn();
      setGovernanceMessage(success);
      await fetchData();
    } catch (e) {
      setGovernanceMessage(toUserFacingError(e, { subject: "Model governance", action: "apply governance action" }));
    } finally {
      setGovernanceBusy(false);
    }
  };

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex items-center justify-between gap-4">
        <PageTitle module="analytics">Analytics</PageTitle>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-gray-500">Time Range:</span>
          <div className="flex bg-surface-800 rounded-lg border border-surface-700 overflow-hidden">
            {HOURS_OPTIONS.map((h) => (
              <button
                key={h}
                onClick={() => setHours(h)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  hours === h
                    ? "bg-brand-600 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                {h}h
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm space-y-1">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
        </div>
      )}

      {/* Volume KPI */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <div className="text-xs text-gray-400 mb-1">Total Volume</div>
          <div className="text-2xl font-bold text-brand-400">
            {totalVolume.toLocaleString()}
          </div>
        </div>
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <div className="text-xs text-gray-400 mb-1">Avg Hourly</div>
          <div className="text-2xl font-bold text-gray-200">
            {aggregatedHourly.length
              ? Math.round(totalVolume / aggregatedHourly.length).toLocaleString()
              : "—"}
          </div>
        </div>
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <div className="text-xs text-gray-400 mb-1">Peak Hour</div>
          <div className="text-2xl font-bold text-amber-400">
            {aggregatedHourly.length
              ? Math.max(...aggregatedHourly.map((h) => h.total)).toLocaleString()
              : "—"}
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <>
          {scorecard && (
            <div className="bg-surface-900 border border-surface-700 rounded-xl p-5 space-y-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 space-y-1">
                  <h2 className="text-sm font-semibold text-gray-300">Decision scorecard</h2>
                  <p className="text-xs text-gray-500">
                    Tenant <span className="font-mono text-gray-400">{scorecard.tenant_id}</span> · last{" "}
                    {scorecard.window_days} day{scorecard.window_days === 1 ? "" : "s"} · from analytics-sink{" "}
                    <code className="text-gray-600">GET /v1/analytics/scorecard</code>
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 shrink-0">
                  <button
                    type="button"
                    className="px-2.5 py-1 rounded-lg border border-surface-600 bg-surface-800 text-xs text-gray-300 hover:bg-surface-700 hover:text-gray-100"
                    onClick={() =>
                      void copyScorecardText(
                        JSON.stringify(buildScorecardExportBundle(scorecard), null, 2),
                        "Copied scorecard JSON",
                      )
                    }
                  >
                    Copy JSON
                  </button>
                  <button
                    type="button"
                    className="px-2.5 py-1 rounded-lg border border-surface-600 bg-surface-800 text-xs text-gray-300 hover:bg-surface-700 hover:text-gray-100"
                    onClick={() =>
                      void copyScorecardText(
                        buildScorecardDiscussionMarkdown(scorecard),
                        "Copied Discussion markdown",
                      )
                    }
                  >
                    Copy for Discussions
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="rounded-lg border border-surface-700 bg-surface-950/60 px-4 py-3">
                  <div className="text-[11px] text-gray-500 uppercase tracking-wide">Total events</div>
                  <div className="text-xl font-semibold text-gray-100 tabular-nums">
                    {scorecard.total_events.toLocaleString()}
                  </div>
                </div>
                <div className="rounded-lg border border-surface-700 bg-surface-950/60 px-4 py-3">
                  <div className="text-[11px] text-gray-500 uppercase tracking-wide">Deny rate</div>
                  <div className="text-xl font-semibold text-rose-300 tabular-nums">
                    {scorecard.deny_rate_pct.toFixed(2)}%
                  </div>
                </div>
                <div className="rounded-lg border border-surface-700 bg-surface-950/60 px-4 py-3">
                  <div className="text-[11px] text-gray-500 uppercase tracking-wide">Decisions in window</div>
                  <div className="text-sm text-gray-400">
                    {scorecard.per_decision.map((d) => (
                      <span key={d.decision} className="mr-3 inline-block">
                        <span className="text-gray-500">{d.decision}:</span>{" "}
                        <span className="text-gray-200 tabular-nums">{d.event_count}</span>
                        <span className="text-gray-600"> ({d.event_pct}%)</span>
                      </span>
                    ))}
                  </div>
                </div>
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <div>
                  <h3 className="text-xs font-medium text-gray-500 mb-2">Per decision</h3>
                  <div className="overflow-x-auto rounded-lg border border-surface-800">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-gray-500 border-b border-surface-800 bg-surface-950/80">
                          <th className="text-left py-2 px-3 font-medium">Decision</th>
                          <th className="text-right py-2 px-3 font-medium">Count</th>
                          <th className="text-right py-2 px-3 font-medium">%</th>
                          <th className="text-right py-2 px-3 font-medium">Avg score</th>
                        </tr>
                      </thead>
                      <tbody>
                        {scorecard.per_decision.map((row) => (
                          <tr key={row.decision} className="border-b border-surface-800/80">
                            <td className="py-2 px-3 text-gray-300">{row.decision}</td>
                            <td className="py-2 px-3 text-right text-gray-200 tabular-nums">{row.event_count}</td>
                            <td className="py-2 px-3 text-right text-gray-400 tabular-nums">{row.event_pct}</td>
                            <td className="py-2 px-3 text-right text-gray-300 tabular-nums">
                              {row.avg_score.toFixed(1)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div>
                  <h3 className="text-xs font-medium text-gray-500 mb-2">Top rule hits</h3>
                  <div className="overflow-x-auto rounded-lg border border-surface-800">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-gray-500 border-b border-surface-800 bg-surface-950/80">
                          <th className="text-left py-2 px-3 font-medium">Rule</th>
                          <th className="text-right py-2 px-3 font-medium">Hits</th>
                        </tr>
                      </thead>
                      <tbody>
                        {scorecard.top_rule_hits.map((raw, i) => {
                          const rid = String(raw.rule_id ?? raw["rule_id"] ?? "");
                          const hits = raw.hit_count ?? raw["hit_count"];
                          return (
                            <tr key={`${rid}-${i}`} className="border-b border-surface-800/80">
                              <td className="py-2 px-3 font-mono text-gray-300">{rid || "—"}</td>
                              <td className="py-2 px-3 text-right text-gray-200 tabular-nums">
                                {typeof hits === "number" ? hits : String(hits ?? "—")}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {scorecard.top_rule_hits.length === 0 && (
                    <p className="text-xs text-gray-600 mt-2">No rule hit aggregates in this window.</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Stacked Bar: Hourly Decisions */}
          <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-300 mb-4">
              Hourly Decisions (Stacked)
            </h2>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={aggregatedHourly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2233" />
                <XAxis
                  dataKey="hour"
                  stroke="#6b7280"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: string) => {
                    const d = new Date(v);
                    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, "0")}:00`;
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
                <Bar
                  dataKey="allow"
                  stackId="dec"
                  fill="#22c55e"
                  radius={[0, 0, 0, 0]}
                />
                <Bar
                  dataKey="review"
                  stackId="dec"
                  fill="#f59e0b"
                  radius={[0, 0, 0, 0]}
                />
                <Bar
                  dataKey="deny"
                  stackId="dec"
                  fill="#ef4444"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
            <div className="flex gap-4 mt-2 justify-center">
              <Legend color="#22c55e" label="Allow" />
              <Legend color="#f59e0b" label="Review" />
              <Legend color="#ef4444" label="Deny" />
            </div>
          </div>

          {/* Decision Volume Over Time */}
          <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-300 mb-4">
              Decision Volume Over Time
            </h2>
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={aggregatedHourly}>
                <defs>
                  <linearGradient id="volumeGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
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
                <Area
                  type="monotone"
                  dataKey="total"
                  stroke="#3b82f6"
                  fill="url(#volumeGrad)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Top Entities Table */}
          <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-300 mb-4">
              Top Entities by Risk
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-400 border-b border-surface-700">
                    <th className="text-left py-2 px-3 font-medium">#</th>
                    <th className="text-left py-2 px-3 font-medium">
                      Entity ID
                    </th>
                    <th className="text-right py-2 px-3 font-medium">
                      Decisions
                    </th>
                    <th className="text-right py-2 px-3 font-medium">
                      Denials
                    </th>
                    <th className="text-right py-2 px-3 font-medium">
                      Avg Score
                    </th>
                    <th className="text-right py-2 px-3 font-medium">
                      Risk Level
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {topEntities.map((entity, i) => (
                    <tr
                      key={entity.entity_id}
                      className="border-b border-surface-800 hover:bg-surface-800/50"
                    >
                      <td className="py-2.5 px-3 text-gray-500">{i + 1}</td>
                      <td className="py-2.5 px-3 font-mono text-xs text-gray-300">
                        {entity.entity_id}
                      </td>
                      <td className="py-2.5 px-3 text-right text-gray-300">
                        {entity.cnt}
                      </td>
                      <td className="py-2.5 px-3 text-right text-red-400">
                        {entity.cnt}
                      </td>
                      <td className="py-2.5 px-3 text-right text-gray-300">
                        {entity.avg_score.toFixed(1)}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <RiskPill score={entity.avg_score} />
                      </td>
                    </tr>
                  ))}
                  {topEntities.length === 0 && (
                    <tr>
                      <td
                        colSpan={6}
                        className="py-8 text-center text-gray-500"
                      >
                        No entity data available
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Model Governance */}
          <div className="bg-surface-900 border border-surface-700 rounded-xl p-5 space-y-4">
            <h2 className="text-sm font-semibold text-gray-300">Model Governance</h2>
            {governanceMessage && (
              <div className="text-xs text-gray-400">{governanceMessage}</div>
            )}
            {groupedModels.map(([modelName, versions]) => (
              <div key={modelName} className="border border-surface-700 rounded-lg p-3 space-y-3">
                <div className="text-sm text-gray-200 font-medium">{modelName}</div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-gray-500 border-b border-surface-700">
                        <th className="text-left py-2">Version</th>
                        <th className="text-left py-2">Weight</th>
                        <th className="text-left py-2">Approved</th>
                        <th className="text-left py-2">Active</th>
                        <th className="text-left py-2">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {versions.map((v) => (
                        <tr key={`${modelName}-${v.version}`} className="border-b border-surface-800">
                          <td className="py-2 text-gray-300">v{v.version}</td>
                          <td className="py-2 text-gray-400">{v.traffic_weight}%</td>
                          <td className="py-2 text-gray-400">{v.metadata?.approved ? "yes" : "no"}</td>
                          <td className="py-2 text-gray-400">{v.active ? "yes" : "no"}</td>
                          <td className="py-2">
                            <div className="flex gap-2">
                              <button
                                disabled={governanceBusy}
                                onClick={() => runGovernance(() => ml.approve(modelName, v.version, "analyst-ui", "approved"), `Approved ${modelName} v${v.version}`)}
                                className="px-2 py-1 rounded bg-surface-700 text-gray-200 hover:bg-surface-600 disabled:opacity-50"
                              >
                                Approve
                              </button>
                              <button
                                disabled={governanceBusy}
                                onClick={() => runGovernance(() => ml.activate(modelName, v.version), `Activated ${modelName} v${v.version}`)}
                                className="px-2 py-1 rounded bg-brand-700 text-white hover:bg-brand-600 disabled:opacity-50"
                              >
                                Activate
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex gap-2">
                  <button
                    disabled={governanceBusy || versions.length < 2}
                    onClick={() => {
                      const latest = versions[versions.length - 1];
                      const previous = versions[versions.length - 2];
                      void runGovernance(
                        () => ml.setTrafficSplit(modelName, { [previous.version]: 20, [latest.version]: 80 }),
                        `Set canary split for ${modelName}`,
                      );
                    }}
                    className="px-3 py-1.5 text-xs rounded bg-amber-700 text-white hover:bg-amber-600 disabled:opacity-50"
                  >
                    Set Canary 80/20
                  </button>
                  <button
                    disabled={governanceBusy}
                    onClick={() => runGovernance(() => ml.rollback(modelName), `Rolled back ${modelName}`)}
                    className="px-3 py-1.5 text-xs rounded bg-red-700 text-white hover:bg-red-600 disabled:opacity-50"
                  >
                    Rollback
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
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

function RiskPill({ score }: { score: number }) {
  let cls = "bg-green-500/20 text-green-400";
  let label = "Low";
  if (score >= 80) {
    cls = "bg-red-500/20 text-red-400";
    label = "Critical";
  } else if (score >= 60) {
    cls = "bg-orange-500/20 text-orange-400";
    label = "High";
  } else if (score >= 40) {
    cls = "bg-amber-500/20 text-amber-400";
    label = "Medium";
  }
  return (
    <span
      className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${cls}`}
    >
      {label}
    </span>
  );
}
