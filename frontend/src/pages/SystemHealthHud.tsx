import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { integrations, type SystemHealthHudResponse } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const POLL_MS = 2500;

function clampPct(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.min(100, Math.max(0, n));
}

function redisLatencyTone(latencyMs: number | null, reachable: boolean): "ok" | "warn" | "bad" | "na" {
  if (!reachable || latencyMs == null) return "na";
  if (latencyMs < 2) return "ok";
  if (latencyMs < 12) return "warn";
  return "bad";
}

function ollamaDepthTone(depth: number, reachable: boolean): "ok" | "warn" | "bad" | "na" {
  if (!reachable) return "na";
  if (depth <= 1) return "ok";
  if (depth <= 4) return "warn";
  return "bad";
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

export default function SystemHealthHud(): ReactElement {
  const [data, setData] = useState<SystemHealthHudResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useRegisterPageMeta({ title: "System health HUD", subtitle: "M5 Pro · Redis · Ollama" });

  const load = useCallback(async (silent: boolean) => {
    if (silent) setRefreshing(true);
    else setLoading(true);
    try {
      const res = await integrations.systemHealthHud();
      setData(res);
      setError(null);
    } catch (e) {
      if (!silent) setData(null);
      setError(toUserFacingError(e, { subject: "System health HUD", action: "pull edge metrics" }));
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

  const ramPct = data ? clampPct(data.host.ram_used_pct) : 0;
  const redisTone = data ? redisLatencyTone(data.redis.latency_ms, data.redis.reachable) : "na";
  const ollamaTone = data ? ollamaDepthTone(data.ollama.queue_depth, data.ollama.reachable) : "na";

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="compliance">System health HUD</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Live edge snapshot for the analyst workstation: <strong className="text-gray-400">Apple M5 Pro</strong>{" "}
            unified memory, <strong className="text-gray-400">Redis</strong> round-trip latency, and{" "}
            <strong className="text-gray-400">Ollama</strong> request queue depth. Wired to{" "}
            <code className="text-gray-400">GET /api/ingress/v1/ops/system-health-hud</code> (integration-ingress / host
            agent).
          </p>
          <p className="text-[11px] text-gray-600 mt-2">
            Poll every {POLL_MS / 1000}s when this tab is visible
            {data?.updated_at ? (
              <>
                {" "}
                · last payload <span className="font-mono text-gray-500">{data.updated_at}</span>
              </>
            ) : null}
            {data?.source === "mock" ? (
              <span className="ml-2 text-amber-500/90">· dev mock</span>
            ) : null}
            {refreshing ? <span className="ml-2 text-gray-500">· refreshing…</span> : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 shrink-0">
          <Link
            to="/ops/system-benchmarking"
            className="text-xs font-semibold px-3 py-2 rounded-lg border border-brand-500/35 bg-brand-950/30 text-brand-200 hover:bg-brand-900/40"
          >
            Sub-ms benchmarking
          </Link>
          <Link
            to="/ops/infra"
            className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700"
          >
            Full infra probes
          </Link>
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/35 bg-rose-950/30 px-4 py-3 text-sm text-rose-200 space-y-2">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
          />
        </div>
      ) : null}

      {loading && !data ? (
        <div className="flex justify-center py-24">
          <div className="w-10 h-10 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : data ? (
        <div className="grid gap-4 md:grid-cols-3">
          <section
            aria-label="M5 Pro memory"
            className={`rounded-2xl border bg-surface-900/80 p-5 space-y-4 ${toneBorder(
              ramPct >= 88 ? "bad" : ramPct >= 72 ? "warn" : "ok",
            )}`}
          >
            <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Host RAM</div>
            <div className="text-2xl font-bold text-gray-100 leading-tight">{data.host.chip_model}</div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm text-gray-400">
                <span>
                  {data.host.ram_used_gb.toFixed(1)} GB / {data.host.ram_total_gb.toFixed(0)} GB
                </span>
                <span className="font-mono tabular-nums text-gray-200">{ramPct.toFixed(0)}%</span>
              </div>
              <div className="h-3 rounded-full bg-surface-800 overflow-hidden border border-surface-700">
                <div
                  className={`h-full rounded-full transition-[width] duration-300 ${
                    ramPct >= 88 ? "bg-rose-500/90" : ramPct >= 72 ? "bg-amber-500/85" : "bg-emerald-500/85"
                  }`}
                  style={{ width: `${ramPct}%` }}
                />
              </div>
            </div>
            {data.host.memory_pressure != null && Number.isFinite(data.host.memory_pressure) ? (
              <p className="text-[11px] text-gray-500">
                Memory pressure (kernel):{" "}
                <span className="font-mono text-gray-400">{(data.host.memory_pressure * 100).toFixed(0)}%</span>
              </p>
            ) : null}
          </section>

          <section
            aria-label="Redis latency"
            className={`rounded-2xl border bg-surface-900/80 p-5 space-y-4 ${toneBorder(redisTone)}`}
          >
            <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Redis</div>
            <div className={`text-4xl font-bold tabular-nums tracking-tight ${toneText(redisTone)}`}>
              {data.redis.reachable && data.redis.latency_ms != null ? (
                <>
                  {data.redis.latency_ms < 10 ? data.redis.latency_ms.toFixed(2) : data.redis.latency_ms.toFixed(1)}
                  <span className="text-lg font-semibold text-gray-500 ml-1">ms</span>
                </>
              ) : (
                <span className="text-gray-500">—</span>
              )}
            </div>
            <p className="text-sm text-gray-400">
              {data.redis.reachable ? "PING RTT (edge → Redis)" : "Unreachable — check socket and ACLs."}
            </p>
            {data.redis.endpoint_hint ? (
              <p className="text-[11px] font-mono text-gray-500 truncate" title={data.redis.endpoint_hint}>
                {data.redis.endpoint_hint}
              </p>
            ) : null}
          </section>

          <section
            aria-label="Ollama queue"
            className={`rounded-2xl border bg-surface-900/80 p-5 space-y-4 ${toneBorder(ollamaTone)}`}
          >
            <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Ollama queue</div>
            <div className={`text-4xl font-bold tabular-nums tracking-tight ${toneText(ollamaTone)}`}>
              {data.ollama.reachable ? data.ollama.queue_depth : "—"}
            </div>
            <p className="text-sm text-gray-400">
              {data.ollama.reachable
                ? "Pending local inference requests (daemon queue)."
                : "Sidecar offline — start Ollama or check Shadow LLM forensics URL."}
            </p>
            {data.ollama.model_loaded ? (
              <p className="text-[11px] font-mono text-gray-500 truncate" title={data.ollama.model_loaded}>
                Loaded: {data.ollama.model_loaded}
              </p>
            ) : null}
          </section>
        </div>
      ) : null}

      <p className="text-[11px] text-gray-600 max-w-2xl leading-relaxed">
        Production should expose this JSON from a read-only host agent (no secrets). Thresholds shown are defaults for
        demo HUDs — tune in integration-ingress to match your SLOs.
      </p>
    </div>
  );
}
