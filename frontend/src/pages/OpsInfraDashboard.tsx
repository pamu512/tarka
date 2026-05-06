import { useCallback, useEffect, useMemo, useState } from "react";
import { PageTitle } from "../components/PageTitle";
import { parsePrometheusText, type PrometheusDigest } from "../utils/parsePrometheusText";

const POLL_MS = 5000;
const FETCH_TIMEOUT_MS = 4500;

type ServiceDef = {
  id: string;
  label: string;
  /** When true, HTTP 5xx / timeout / network error triggers global critical alert. */
  critical: boolean;
  healthUrl: string;
  metricsUrl: string;
  /** Optional core-api-only process stats (RSS / worker hint). */
  processStatsUrl?: string;
};

const SERVICES: ServiceDef[] = [
  {
    id: "core",
    label: "Core API",
    critical: true,
    healthUrl: "/api/core/v1/health",
    metricsUrl: "/api/core/metrics",
    processStatsUrl: "/api/core/v1/infra/process-stats",
  },
  {
    id: "decisions",
    label: "Decision API",
    critical: true,
    healthUrl: "/api/decisions/v1/health",
    metricsUrl: "/api/decisions/metrics",
  },
  {
    id: "cases",
    label: "Case API",
    critical: true,
    healthUrl: "/api/cases/v1/health",
    metricsUrl: "/api/cases/metrics",
  },
  {
    id: "signal",
    label: "Signal API",
    critical: true,
    healthUrl: "/api/signal-plane/v1/health",
    metricsUrl: "/api/signal-plane/metrics",
  },
  {
    id: "graph",
    label: "Graph service",
    critical: true,
    healthUrl: "/api/graph/v1/health",
    metricsUrl: "/api/graph/metrics",
  },
  {
    id: "data-plane",
    label: "Data plane",
    critical: true,
    healthUrl: "/api/analytics/v1/health",
    metricsUrl: "/api/analytics/metrics",
  },
  {
    id: "investigation",
    label: "Investigation agent",
    critical: false,
    healthUrl: "/api/investigation/v1/health",
    metricsUrl: "/api/investigation/metrics",
  },
  {
    id: "ingress",
    label: "Integration ingress",
    critical: false,
    healthUrl: "/api/ingress/v1/health",
    metricsUrl: "/api/ingress/metrics",
  },
];

type ProbeOutcome = "ok" | "warn" | "fail" | "pending";

type ServiceSnapshot = {
  outcome: ProbeOutcome;
  healthHttp: number | null;
  healthBody: string;
  metricsHttp: number | null;
  metricsDigest: PrometheusDigest | null;
  rssMb: number | null;
  workersHint: number | null;
  error: string | null;
  at: number;
};

function fetchWithTimeout(url: string, ms: number): Promise<Response> {
  const ac = new AbortController();
  const t = window.setTimeout(() => ac.abort(), ms);
  return fetch(url, { signal: ac.signal }).finally(() => window.clearTimeout(t));
}

async function readJsonSafe(res: Response): Promise<unknown> {
  const t = await res.text();
  try {
    return JSON.parse(t) as unknown;
  } catch {
    return { raw: t.slice(0, 400) };
  }
}

export default function OpsInfraDashboard() {
  const [snap, setSnap] = useState<Record<string, ServiceSnapshot>>({});
  const [lastRunAt, setLastRunAt] = useState<number | null>(null);

  const probeOne = useCallback(async (svc: ServiceDef) => {
    let outcome: ProbeOutcome = "ok";
    let healthHttp: number | null = null;
    let healthBody = "";
    let metricsHttp: number | null = null;
    let metricsDigest: PrometheusDigest | null = null;
    let rssMb: number | null = null;
    let workersHint: number | null = null;
    let error: string | null = null;
    let hardFailed = false;

    const markFail = (msg: string) => {
      hardFailed = true;
      outcome = "fail";
      error = msg;
    };

    try {
      const hRes = await fetchWithTimeout(svc.healthUrl, FETCH_TIMEOUT_MS);
      healthHttp = hRes.status;
      healthBody = JSON.stringify(await readJsonSafe(hRes));
      if (!hRes.ok) {
        if (hRes.status >= 500) markFail(`Health HTTP ${hRes.status}`);
        else outcome = "warn";
      }
    } catch (e) {
      markFail(e instanceof Error ? (e.name === "AbortError" ? "Health check timed out" : e.message) : "Health failed");
    }

    if (!hardFailed) {
      try {
        const mRes = await fetchWithTimeout(svc.metricsUrl, FETCH_TIMEOUT_MS);
        metricsHttp = mRes.status;
        if (mRes.ok) {
          const txt = await mRes.text();
          metricsDigest = parsePrometheusText(txt);
        } else if (mRes.status >= 500) {
          markFail(`Prometheus HTTP ${mRes.status}`);
        } else {
          outcome = outcome === "ok" ? "warn" : outcome;
        }
      } catch (e) {
        markFail(
          e instanceof Error ? (e.name === "AbortError" ? "Prometheus scrape timed out" : e.message) : "Metrics failed",
        );
      }
    }

    if (svc.processStatsUrl && !hardFailed) {
      try {
        const pRes = await fetchWithTimeout(svc.processStatsUrl, FETCH_TIMEOUT_MS);
        if (pRes.ok) {
          const j = (await readJsonSafe(pRes)) as Record<string, unknown>;
          const mb = j.rss_mb;
          const wh = j.worker_processes_hint;
          if (typeof mb === "number") rssMb = mb;
          if (typeof wh === "number") workersHint = wh;
        }
      } catch {
        /* optional */
      }
    }

    setSnap((prev) => ({
      ...prev,
      [svc.id]: {
        outcome,
        healthHttp,
        healthBody,
        metricsHttp,
        metricsDigest,
        rssMb,
        workersHint,
        error,
        at: Date.now(),
      },
    }));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      await Promise.all(SERVICES.map((s) => probeOne(s)));
      if (!cancelled) setLastRunAt(Date.now());
    };
    void run();
    const id = window.setInterval(() => {
      void run();
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [probeOne]);

  const criticalDown = useMemo(() => {
    return SERVICES.some((s) => {
      if (!s.critical) return false;
      const st = snap[s.id];
      if (!st) return false;
      if (st.outcome === "fail") return true;
      if (st.healthHttp != null && st.healthHttp >= 500) return true;
      if (st.metricsHttp != null && st.metricsHttp >= 500) return true;
      return false;
    });
  }, [snap]);

  return (
    <div className="relative p-6 space-y-6 animate-fade-in min-h-full">
      {criticalDown ? (
        <>
          <div
            className="fixed inset-0 z-[300] pointer-events-none border-4 border-red-500 shadow-[inset_0_0_120px_rgba(220,38,38,0.22)] animate-pulse motion-reduce:animate-none"
            aria-hidden
          />
          <div
            role="alert"
            aria-live="assertive"
            className="fixed top-0 left-0 right-0 z-[301] px-4 py-3 text-center text-sm font-semibold text-white bg-red-600 shadow-lg animate-pulse motion-reduce:animate-none"
          >
            Critical service degradation — check Signal API, Core API, or Data plane (HTTP 5xx or timeout).
          </div>
        </>
      ) : null}

      <div className={criticalDown ? "pt-10" : ""}>
        <PageTitle module="compliance">Infrastructure &amp; health</PageTitle>
        <p className="text-sm text-gray-500 mt-2 max-w-3xl">
          Live probes every {POLL_MS / 1000}s: JSON <code className="text-gray-400">/v1/health</code> and Prometheus{" "}
          <code className="text-gray-400">/metrics</code> per service. RSS and worker hint are exposed for the Core API
          process only. Queue-style signals are parsed from counter names (ingest, shedding, NATS, Redis, …) when present
          in metrics.
        </p>
        <p className="text-xs text-gray-600 mt-1">
          Last poll completed:{" "}
          {lastRunAt ? `${new Date(lastRunAt).toLocaleTimeString()} (${POLL_MS / 1000}s interval)` : "—"}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {SERVICES.map((svc) => {
          const st = snap[svc.id];
          const oc = st?.outcome ?? "pending";
          const border =
            oc === "fail"
              ? "border-red-500/60"
              : oc === "warn"
                ? "border-amber-500/50"
                : oc === "ok"
                  ? "border-emerald-600/40"
                  : "border-surface-600";
          return (
            <div
              key={svc.id}
              className={`rounded-xl border bg-surface-900/80 p-4 space-y-3 ${border} ${svc.critical && oc === "fail" ? "ring-2 ring-red-500/50" : ""}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-gray-100">{svc.label}</div>
                  {svc.critical ? (
                    <span className="text-[10px] uppercase tracking-wide text-red-300/90">critical path</span>
                  ) : (
                    <span className="text-[10px] uppercase tracking-wide text-gray-600">supporting</span>
                  )}
                </div>
                <span
                  className={`text-xs font-mono px-2 py-0.5 rounded ${
                    oc === "ok"
                      ? "bg-emerald-900/50 text-emerald-200"
                      : oc === "warn"
                        ? "bg-amber-900/40 text-amber-200"
                        : oc === "fail"
                          ? "bg-red-900/50 text-red-200"
                          : "bg-surface-800 text-gray-500"
                  }`}
                >
                  {oc}
                </span>
              </div>

              <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                <dt className="text-gray-500">Health HTTP</dt>
                <dd className="text-gray-200 font-mono text-right">{st?.healthHttp ?? "—"}</dd>
                <dt className="text-gray-500">Prometheus HTTP</dt>
                <dd className="text-gray-200 font-mono text-right">{st?.metricsHttp ?? "—"}</dd>
                <dt className="text-gray-500">Memory (RSS)</dt>
                <dd className="text-gray-200 text-right">
                  {st?.rssMb != null ? `${st.rssMb} MB` : "—"}
                  {svc.id !== "core" ? <span className="text-gray-600 block">core-api only</span> : null}
                </dd>
                <dt className="text-gray-500">Workers (hint)</dt>
                <dd className="text-gray-200 text-right">{st?.workersHint ?? "—"}</dd>
                <dt className="text-gray-500">HTTP requests (Σ)</dt>
                <dd className="text-gray-200 font-mono text-right">
                  {st?.metricsDigest?.httpRequestsTotal ?? "—"}
                </dd>
                <dt className="text-gray-500">HTTP 5xx (Σ)</dt>
                <dd className="text-gray-200 font-mono text-right">
                  {st?.metricsDigest?.httpServerErrorsTotal ?? "—"}
                </dd>
              </dl>

              <div>
                <div className="text-[11px] font-medium text-gray-500 mb-1">Queue / backlog counters</div>
                {st?.metricsDigest && st.metricsDigest.notableCounters.length > 0 ? (
                  <ul className="text-[11px] font-mono text-gray-400 space-y-0.5 max-h-28 overflow-y-auto">
                    {st.metricsDigest.notableCounters.map((c) => (
                      <li key={c.name} className="flex justify-between gap-2">
                        <span className="truncate" title={c.name}>
                          {c.name}
                        </span>
                        <span className="shrink-0 text-gray-300">{c.value}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[11px] text-gray-600">No matching counters in this scrape.</p>
                )}
              </div>

              {st?.error ? (
                <p className="text-xs text-red-300/95 border border-red-500/30 rounded px-2 py-1.5 bg-red-950/40">
                  {st.error}
                </p>
              ) : null}

              <details className="text-xs">
                <summary className="cursor-pointer text-gray-500 hover:text-gray-400">Health JSON</summary>
                <pre className="mt-2 max-h-32 overflow-auto text-[10px] text-gray-500 bg-surface-950 rounded p-2 border border-surface-800">
                  {st?.healthBody ? st.healthBody : "…"}
                </pre>
              </details>
            </div>
          );
        })}
      </div>
    </div>
  );
}
