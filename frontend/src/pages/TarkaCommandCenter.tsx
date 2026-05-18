import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { integrations, type CommandCenterModuleTile, type CommandCenterResponse } from "../api/client";
import { ModuleIcon, type ModuleId } from "../components/ModuleIcon";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { TarkaLogo } from "../components/TarkaLogo";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const TONE_BORDER: Record<string, string> = {
  amber: "border-amber-500/35 hover:border-amber-500/55",
  violet: "border-violet-500/35 hover:border-violet-500/55",
  fuchsia: "border-fuchsia-500/35 hover:border-fuchsia-500/55",
  rose: "border-rose-500/35 hover:border-rose-500/55",
  orange: "border-orange-500/35 hover:border-orange-500/55",
  cyan: "border-cyan-500/35 hover:border-cyan-500/55",
  teal: "border-teal-500/35 hover:border-teal-500/55",
  elevated: "border-amber-500/40 hover:border-amber-500/60",
  critical: "border-rose-500/45 hover:border-rose-500/65",
  normal: "border-surface-600 hover:border-surface-500",
};

const PRIORITY_DOT: Record<string, string> = {
  high: "bg-rose-400",
  elevated: "bg-amber-400",
};

export default function TarkaCommandCenter(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<CommandCenterResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useRegisterPageMeta({ title: "Command Center", subtitle: "Unified cockpit" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrations.commandCenter({ tenant_id: tenantId });
      setData(res);
      setError(null);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Command Center", action: "load cockpit" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const modules = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q || !data) return data?.modules ?? [];
    return data.modules.filter(
      (m) =>
        m.title.toLowerCase().includes(q) ||
        m.metric_label.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q),
    );
  }, [data, filter]);

  return (
    <div className="min-h-full bg-gradient-to-b from-surface-950 via-surface-950 to-surface-900">
      <div className="p-6 space-y-6 max-w-7xl mx-auto animate-fade-in">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-4">
            <TarkaLogo className="h-10 w-auto opacity-90 shrink-0 mt-1" />
            <div>
              <PageTitle module="dashboard">Tarka Command Center</PageTitle>
              <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
                Unified analyst cockpit — queue depth, fraud signals, marketplace controls, and compliance toggles in
                one surface. Use <kbd className="px-1.5 py-0.5 rounded bg-surface-800 border border-surface-600 text-[10px] font-mono text-gray-300">⌘K</kbd> to jump anywhere.
              </p>
              <p className="text-[11px] text-gray-600 mt-2 font-mono">
                GET /api/ingress/v1/ops/command-center · tenant{" "}
                <span className="text-gray-400">{tenantId}</span>
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 shrink-0">
            <Link
              to="/dashboard"
              className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-300 hover:bg-surface-700"
            >
              Classic dashboard
            </Link>
            <button
              type="button"
              disabled={loading}
              onClick={() => void load()}
              className="text-xs font-semibold px-3 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white disabled:opacity-50"
            >
              {loading ? "Syncing…" : "Refresh cockpit"}
            </button>
          </div>
        </header>

        {error ? (
          <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
            {error}
            <SupportIdHint className="mt-2" />
          </div>
        ) : null}

        {loading && !data ? (
          <p className="text-sm text-gray-500 py-20 text-center">Assembling command center…</p>
        ) : data ? (
          <>
            <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {data.hero_kpis.map((kpi) => (
                <Link
                  key={kpi.id}
                  to={kpi.route}
                  className={`rounded-xl border bg-surface-900/70 px-4 py-4 transition-colors ${TONE_BORDER[kpi.tone] ?? TONE_BORDER.normal}`}
                >
                  <p className="text-[10px] uppercase tracking-wide text-gray-500">{kpi.label}</p>
                  <p className="text-3xl font-bold tabular-nums text-gray-100 mt-1">{kpi.value}</p>
                  <p className="text-[11px] text-gray-500 mt-1">{kpi.delta}</p>
                </Link>
              ))}
            </section>

            {data.action_queue.length > 0 ? (
              <section className="rounded-xl border border-amber-500/25 bg-amber-950/10 overflow-hidden">
                <div className="px-4 py-3 border-b border-amber-500/20 flex justify-between items-center">
                  <h2 className="text-sm font-semibold text-amber-100/90">Action queue</h2>
                  <span className="text-[11px] text-amber-200/60">{data.action_queue.length} items</span>
                </div>
                <ul className="divide-y divide-amber-500/10">
                  {data.action_queue.map((item) => (
                    <li key={item.id}>
                      <Link
                        to={item.route}
                        className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-amber-950/20 transition-colors"
                      >
                        <span
                          className={`h-2 w-2 rounded-full shrink-0 ${PRIORITY_DOT[item.priority] ?? "bg-gray-500"}`}
                          aria-hidden
                        />
                        <div className="flex-1 min-w-[200px]">
                          <p className="text-sm font-medium text-gray-200">{item.title}</p>
                          <p className="text-[11px] text-gray-500">{item.description}</p>
                        </div>
                        <ModuleIcon module={item.module as ModuleId} className="w-4 h-4 text-gray-500" />
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <div className="flex flex-wrap gap-3 items-center">
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter modules…"
                className="flex-1 min-w-[200px] max-w-md rounded-lg border border-surface-600 bg-surface-900 px-3 py-2 text-sm text-gray-100"
              />
              <div className="flex flex-wrap gap-2">
                {data.quick_links.map((link) =>
                  link.route === "#palette" ? (
                    <span
                      key={link.label}
                      className="text-[11px] px-2.5 py-1 rounded-full border border-surface-600 text-gray-500"
                      title={link.hint}
                    >
                      {link.label} {link.hint}
                    </span>
                  ) : (
                    <Link
                      key={link.route}
                      to={link.route}
                      className="text-[11px] font-medium px-2.5 py-1 rounded-full border border-surface-600 text-gray-400 hover:text-brand-300 hover:border-brand-500/40"
                    >
                      {link.label}
                    </Link>
                  ),
                )}
              </div>
            </div>

            <section>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">
                All modules ({modules.length})
              </h2>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {modules.map((tile) => (
                  <ModuleTile key={tile.id} tile={tile} />
                ))}
              </div>
            </section>

            <p className="text-[10px] text-gray-600 text-right">
              Last sync {new Date(data.updated_at).toLocaleString()}
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}

function ModuleTile({ tile }: { tile: CommandCenterModuleTile }): ReactElement {
  const tone = TONE_BORDER[tile.tone] ?? TONE_BORDER.normal;
  return (
    <Link
      to={tile.route}
      className={`rounded-xl border bg-surface-900/60 p-4 flex flex-col gap-3 transition-all hover:bg-surface-800/50 ${tone}`}
    >
      <div className="flex items-start justify-between gap-2">
        <ModuleIcon module={tile.module as ModuleId} className="w-5 h-5 text-brand-400" />
        <span className="text-[10px] text-gray-500 uppercase tracking-wide">{tile.metric_label}</span>
      </div>
      <div>
        <p className="text-sm font-semibold text-gray-100 leading-snug">{tile.title}</p>
        <p className="text-xl font-bold tabular-nums text-gray-200 mt-2">{tile.metric_value}</p>
      </div>
    </Link>
  );
}
