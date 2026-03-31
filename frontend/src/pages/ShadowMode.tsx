import { useEffect, useState, useCallback } from "react";
import { rules, shadow, type RulePack } from "../api/client";

type PackMode = "active" | "shadow" | "disabled";

interface ObservationStats {
  total: number;
  diverged?: number;
  divergence_rate?: number;
  production_distribution?: Record<string, number>;
  shadow_distribution?: Record<string, number>;
  confusion_matrix?: { tp: number; fp: number; fn: number; tn: number };
  avg_score_delta?: number;
  score_delta_p95?: number;
}

interface Observation {
  trace_id: string;
  production_decision: string;
  production_score: number;
  shadow_decision: string;
  shadow_score: number;
  diverged: boolean;
  timestamp: string;
}

export default function ShadowMode() {
  const [packs, setPacks] = useState<(RulePack & { mode?: PackMode })[]>([]);
  const [stats, setStats] = useState<ObservationStats | null>(null);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [togglingPack, setTogglingPack] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [packsRes, statsRes, obsRes] = await Promise.allSettled([
        rules.list(),
        shadow.stats(),
        shadow.observations(200),
      ]);
      if (packsRes.status === "fulfilled") setPacks(packsRes.value.packs ?? packsRes.value as any);
      if (statsRes.status === "fulfilled") setStats(statsRes.value);
      if (obsRes.status === "fulfilled") setObservations((obsRes.value.observations ?? []) as Observation[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load shadow data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 15_000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  async function handleModeChange(filename: string, mode: PackMode) {
    setTogglingPack(filename);
    try {
      await shadow.setPackMode(filename, mode);
      await fetchAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to set mode");
    } finally {
      setTogglingPack(null);
    }
  }

  const divergences = observations.filter((o) => o.diverged);
  const cm = stats?.confusion_matrix;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-brand-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-gray-400 text-sm">Loading shadow data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Shadow / Observation Mode</h1>
          <p className="text-sm text-gray-500 mt-1">
            Compare shadow rule packs against production without affecting live decisions
          </p>
        </div>
        <button
          onClick={() => { setLoading(true); fetchAll(); }}
          className="px-4 py-2 bg-surface-700 hover:bg-surface-600 text-gray-300 text-sm font-medium rounded-lg transition-colors"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <KPICard title="Total Observations" value={String(stats?.total ?? 0)} accent="text-brand-400" />
        <KPICard title="Divergences" value={String(stats?.diverged ?? 0)} accent="text-amber-400" />
        <KPICard
          title="Divergence Rate"
          value={stats?.divergence_rate != null ? `${stats.divergence_rate}%` : "--"}
          accent="text-red-400"
        />
        <KPICard
          title="Avg Score Delta"
          value={stats?.avg_score_delta != null ? (stats.avg_score_delta >= 0 ? "+" : "") + stats.avg_score_delta.toFixed(2) : "--"}
          accent="text-cyan-400"
        />
        <KPICard
          title="P95 Score Delta"
          value={stats?.score_delta_p95 != null ? (stats.score_delta_p95 >= 0 ? "+" : "") + stats.score_delta_p95.toFixed(2) : "--"}
          accent="text-purple-400"
        />
      </div>

      {/* Confusion Matrix */}
      {cm && stats && stats.total > 0 && (
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">
            Confusion Matrix (Shadow as Predictor vs Production)
          </h2>
          <div className="grid grid-cols-2 gap-3 max-w-md">
            <ConfusionCell label="True Positive" value={cm.tp} sub="Both deny" color="text-red-400" bg="bg-red-500/10" />
            <ConfusionCell label="False Positive" value={cm.fp} sub="Shadow denies, prod doesn't" color="text-amber-400" bg="bg-amber-500/10" />
            <ConfusionCell label="False Negative" value={cm.fn} sub="Prod denies, shadow doesn't" color="text-orange-400" bg="bg-orange-500/10" />
            <ConfusionCell label="True Negative" value={cm.tn} sub="Neither deny" color="text-green-400" bg="bg-green-500/10" />
          </div>
        </div>
      )}

      {/* Rule Pack Mode Toggles */}
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Rule Pack Modes</h2>
        {packs.length === 0 ? (
          <p className="text-sm text-gray-500">No rule packs found</p>
        ) : (
          <div className="space-y-3">
            {packs.map((pack) => {
              const file = (pack as any)._file ?? (pack as any).file ?? "";
              const currentMode: PackMode = (pack as any).mode ?? "active";
              const isBusy = togglingPack === file;
              return (
                <div
                  key={file || pack.name}
                  className="flex items-center justify-between bg-surface-800 rounded-lg px-4 py-3"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <ModeIndicator mode={currentMode} />
                      <span className="text-sm text-gray-200 font-medium truncate">
                        {pack.name}
                      </span>
                    </div>
                    <span className="text-xs text-gray-500 ml-5">{file}</span>
                  </div>

                  <div className="flex items-center gap-2 ml-4 flex-shrink-0">
                    <ModeButton
                      label="Active"
                      active={currentMode === "active"}
                      disabled={isBusy}
                      color="bg-green-600"
                      onClick={() => handleModeChange(file, "active")}
                    />
                    <ModeButton
                      label="Shadow"
                      active={currentMode === "shadow"}
                      disabled={isBusy}
                      color="bg-amber-600"
                      onClick={() => handleModeChange(file, "shadow")}
                    />
                    <ModeButton
                      label="Disabled"
                      active={currentMode === "disabled"}
                      disabled={isBusy}
                      color="bg-gray-600"
                      onClick={() => handleModeChange(file, "disabled")}
                    />

                    {currentMode === "shadow" && (
                      <button
                        onClick={() => handleModeChange(file, "active")}
                        disabled={isBusy}
                        className="ml-2 px-3 py-1.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors whitespace-nowrap"
                      >
                        Promote to Active
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Decision Distribution Comparison */}
      {stats && stats.total > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <DistributionCard title="Production Decisions" data={stats.production_distribution} />
          <DistributionCard title="Shadow Decisions" data={stats.shadow_distribution} />
        </div>
      )}

      {/* Divergence Timeline */}
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">
          Recent Divergences
          {divergences.length > 0 && (
            <span className="ml-2 text-xs text-gray-500 font-normal">
              ({divergences.length} of {observations.length} observations)
            </span>
          )}
        </h2>
        <div className="overflow-auto max-h-[400px]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 border-b border-surface-700">
                <th className="text-left py-2 px-2 font-medium">Time</th>
                <th className="text-left py-2 px-2 font-medium">Trace ID</th>
                <th className="text-center py-2 px-2 font-medium">Production</th>
                <th className="text-center py-2 px-2 font-medium">Shadow</th>
                <th className="text-right py-2 px-2 font-medium">Prod Score</th>
                <th className="text-right py-2 px-2 font-medium">Shadow Score</th>
                <th className="text-right py-2 px-2 font-medium">Delta</th>
              </tr>
            </thead>
            <tbody>
              {divergences.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-gray-500">
                    No divergences detected yet
                  </td>
                </tr>
              ) : (
                divergences
                  .slice()
                  .reverse()
                  .slice(0, 50)
                  .map((o, i) => (
                    <tr
                      key={o.trace_id ?? i}
                      className="border-b border-surface-800 hover:bg-surface-800/50"
                    >
                      <td className="py-2 px-2 text-gray-500 text-xs whitespace-nowrap">
                        {new Date(o.timestamp).toLocaleTimeString()}
                      </td>
                      <td className="py-2 px-2 text-gray-300 font-mono text-xs">
                        {o.trace_id.slice(0, 12)}...
                      </td>
                      <td className="py-2 px-2 text-center">
                        <DecisionBadge decision={o.production_decision} />
                      </td>
                      <td className="py-2 px-2 text-center">
                        <DecisionBadge decision={o.shadow_decision} />
                      </td>
                      <td className="py-2 px-2 text-right text-gray-300">
                        {o.production_score?.toFixed(1)}
                      </td>
                      <td className="py-2 px-2 text-right text-gray-300">
                        {o.shadow_score?.toFixed(1)}
                      </td>
                      <td className="py-2 px-2 text-right">
                        <ScoreDelta value={o.shadow_score - o.production_score} />
                      </td>
                    </tr>
                  ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function KPICard({ title, value, accent }: { title: string; value: string; accent: string }) {
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
      <div className="text-xs text-gray-400 font-medium mb-1">{title}</div>
      <div className={`text-2xl font-bold ${accent}`}>{value}</div>
    </div>
  );
}

function ConfusionCell({ label, value, sub, color, bg }: { label: string; value: number; sub: string; color: string; bg: string }) {
  return (
    <div className={`${bg} border border-surface-700 rounded-lg p-4 text-center`}>
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-[10px] text-gray-500 mt-1">{sub}</div>
    </div>
  );
}

function ModeIndicator({ mode }: { mode: PackMode }) {
  const colors: Record<PackMode, string> = {
    active: "bg-green-500",
    shadow: "bg-amber-500",
    disabled: "bg-gray-500",
  };
  return <span className={`w-2 h-2 rounded-full flex-shrink-0 ${colors[mode]}`} />;
}

function ModeButton({
  label,
  active,
  disabled,
  color,
  onClick,
}: {
  label: string;
  active: boolean;
  disabled: boolean;
  color: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || active}
      className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
        active
          ? `${color} text-white`
          : "bg-surface-700 text-gray-400 hover:bg-surface-600 hover:text-gray-200"
      } disabled:opacity-50`}
    >
      {label}
    </button>
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

function ScoreDelta({ value }: { value: number }) {
  const formatted = (value >= 0 ? "+" : "") + value.toFixed(1);
  const color = value > 0 ? "text-red-400" : value < 0 ? "text-green-400" : "text-gray-400";
  return <span className={`text-xs font-mono font-semibold ${color}`}>{formatted}</span>;
}

function DistributionCard({ title, data }: { title: string; data?: Record<string, number> }) {
  if (!data) return null;
  const entries = Object.entries(data).sort(([a], [b]) => a.localeCompare(b));
  const total = entries.reduce((s, [, v]) => s + v, 0);

  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
      <h2 className="text-sm font-semibold text-gray-300 mb-3">{title}</h2>
      <div className="space-y-2">
        {entries.map(([decision, count]) => {
          const pct = total > 0 ? (count / total) * 100 : 0;
          const barColor: Record<string, string> = {
            allow: "bg-green-500",
            review: "bg-amber-500",
            deny: "bg-red-500",
          };
          return (
            <div key={decision}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-gray-400 capitalize">{decision}</span>
                <span className="text-xs text-gray-400">
                  {count} ({pct.toFixed(1)}%)
                </span>
              </div>
              <div className="h-2 bg-surface-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${barColor[decision] ?? "bg-gray-500"}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
