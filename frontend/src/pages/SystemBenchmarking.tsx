import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { integrations, type SystemBenchmarkProbe, type SystemBenchmarkingResponse } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const POLL_MS = 8000;

function statusTone(status: string): "ok" | "warn" | "bad" | "na" {
  if (status === "on_target") return "ok";
  if (status === "near_target") return "warn";
  if (status === "over_target") return "bad";
  return "na";
}

function toneBorder(t: "ok" | "warn" | "bad" | "na"): string {
  if (t === "ok") return "border-emerald-500/45";
  if (t === "warn") return "border-amber-500/45";
  if (t === "bad") return "border-rose-500/50";
  return "border-surface-600";
}

function toneText(t: "ok" | "warn" | "bad" | "na"): string {
  if (t === "ok") return "text-emerald-300";
  if (t === "warn") return "text-amber-200";
  if (t === "bad") return "text-rose-300";
  return "text-gray-500";
}

function ProbeCard({ probe, targetMs }: { probe: SystemBenchmarkProbe; targetMs: number }): ReactElement {
  const tone = statusTone(probe.status);
  const p95 = probe.p95_ms ?? 0;
  const barPct = targetMs > 0 ? Math.min(100, Math.round((p95 / (targetMs * 3)) * 100)) : 0;
  const targetPct = Math.round((targetMs / (targetMs * 3)) * 100);

  return (
    <article className={`rounded-xl border bg-surface-900/75 p-4 space-y-3 ${toneBorder(tone)}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-gray-200">{probe.label}</p>
          <p className="text-[10px] uppercase tracking-wide text-gray-600 mt-0.5">{probe.plane.replace(/_/g, " ")}</p>
        </div>
        <span
          className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full border ${
            tone === "ok"
              ? "border-emerald-500/40 text-emerald-200"
              : tone === "warn"
                ? "border-amber-500/40 text-amber-200"
                : tone === "bad"
                  ? "border-rose-500/40 text-rose-200"
                  : "border-surface-600 text-gray-500"
          }`}
        >
          {probe.status.replace(/_/g, " ")}
        </span>
      </div>

      <div className="flex items-end gap-3">
        <div className={`text-3xl font-bold tabular-nums ${toneText(tone)}`}>
          {probe.p95_ms != null ? (
            <>
              {probe.p95_ms < 10 ? probe.p95_ms.toFixed(3) : probe.p95_ms.toFixed(2)}
              <span className="text-base font-semibold text-gray-500 ml-1">ms p95</span>
            </>
          ) : (
            <span className="text-gray-500 text-xl">n/a</span>
          )}
        </div>
        {probe.delta_p95_vs_target_ms != null ? (
          <p className="text-xs text-gray-500 pb-1">
            {probe.delta_p95_vs_target_ms <= 0 ? (
              <span className="text-emerald-400/90">
                {(Math.abs(probe.delta_p95_vs_target_ms) * 1000).toFixed(0)}µs under target
              </span>
            ) : (
              <span className="text-rose-300/90">+{probe.delta_p95_vs_target_ms.toFixed(3)} ms vs target</span>
            )}
          </p>
        ) : null}
      </div>

      <div className="relative h-2.5 rounded-full bg-surface-800 border border-surface-700 overflow-hidden">
        <div
          className="absolute top-0 bottom-0 w-px bg-brand-400/80 z-10"
          style={{ left: `${targetPct}%` }}
          title={`Sub-ms target ${targetMs} ms`}
        />
        <div
          className={`h-full rounded-full transition-all ${
            tone === "ok" ? "bg-emerald-500/85" : tone === "warn" ? "bg-amber-500/85" : "bg-rose-500/85"
          }`}
          style={{ width: `${barPct}%` }}
        />
      </div>
      <div className="flex flex-wrap gap-3 text-[10px] font-mono text-gray-600">
        <span>p50 {probe.p50_ms ?? "—"}</span>
        <span>min {probe.min_ms ?? "—"}</span>
        <span>max {probe.max_ms ?? "—"}</span>
        <span>n={probe.sample_count}</span>
      </div>
      {probe.detail ? <p className="text-[10px] text-gray-600 truncate" title={probe.detail}>{probe.detail}</p> : null}
    </article>
  );
}

export default function SystemBenchmarking(): ReactElement {
  const [data, setData] = useState<SystemBenchmarkingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useRegisterPageMeta({ title: "System benchmarking", subtitle: "Sub-millisecond target" });

  const load = useCallback(async (silent: boolean) => {
    if (silent) setRefreshing(true);
    else setLoading(true);
    try {
      const res = await integrations.systemBenchmarking();
      setData(res);
      setError(null);
    } catch (e) {
      if (!silent) setData(null);
      setError(toUserFacingError(e, { subject: "System benchmarking", action: "run latency probes" }));
    } finally {
      if (silent) setRefreshing(false);
      else setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const targetMs = data?.target.p95_target_ms ?? 1;
  const criticalProbes = useMemo(
    () => (data?.probes ?? []).filter((p) => p.critical),
    [data?.probes],
  );

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="compliance">System benchmarking</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Compare live path latency against the <strong className="text-brand-300">Sub-millisecond</strong> product
            target (<span className="font-mono text-gray-400">p95 ≤ {targetMs} ms</span>) across Redis, rule engine,
            decision API, and ingress health probes.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET /api/ingress/v1/ops/system-benchmarking
            {refreshing ? " · refreshing…" : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/ops/system-health"
            className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700"
          >
            System health HUD
          </Link>
          <button
            type="button"
            onClick={() => void load(true)}
            className="text-xs font-semibold px-3 py-2 rounded-lg border border-brand-500/40 bg-brand-950/40 text-brand-200 hover:bg-brand-900/50"
          >
            Re-run probes
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/35 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <div className="flex justify-center py-20">
          <div className="w-10 h-10 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : data ? (
        <>
          <div
            className={`rounded-2xl border px-5 py-4 flex flex-wrap items-center justify-between gap-4 ${
              data.summary.all_critical_on_target
                ? "border-emerald-500/40 bg-emerald-950/20"
                : "border-amber-500/35 bg-amber-950/15"
            }`}
          >
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-500">Sub-millisecond posture</p>
              <p className="text-lg font-semibold text-gray-100 mt-1">
                {data.summary.all_critical_on_target
                  ? "All critical probes on target"
                  : `${data.summary.over_target_count} critical probe(s) over budget`}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {data.summary.on_target_count}/{data.summary.critical_probe_count} critical paths at p95 ≤ {targetMs}{" "}
                ms · {data.methodology.sample_rounds} samples per probe
              </p>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase text-gray-600">Worst critical p95</p>
              <p className="text-2xl font-bold tabular-nums text-gray-200">
                {data.summary.worst_p95_ms != null ? `${data.summary.worst_p95_ms} ms` : "—"}
              </p>
              {data.summary.worst_probe_id ? (
                <p className="text-[10px] font-mono text-gray-500">{data.summary.worst_probe_id}</p>
              ) : null}
            </div>
          </div>

          <section>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">Critical path probes</h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {criticalProbes.map((p) => (
                <ProbeCard key={p.id} probe={p} targetMs={targetMs} />
              ))}
            </div>
          </section>

          <section>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">All probes</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {data.probes
                .filter((p) => !p.critical)
                .map((p) => (
                  <ProbeCard key={p.id} probe={p} targetMs={targetMs} />
                ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
