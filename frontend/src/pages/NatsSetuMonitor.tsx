import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  osint,
  type NatsSetuChannelHealth,
  type NatsSetuMonitorChannel,
  type NatsSetuMonitorResponse,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const POLL_MS = 15_000;

function statusPresentation(status: NatsSetuChannelHealth): {
  label: string;
  dot: string;
  chip: string;
} {
  switch (status) {
    case "healthy":
      return {
        label: "Healthy",
        dot: "bg-emerald-400",
        chip: "border-emerald-500/40 bg-emerald-950/40 text-emerald-200",
      };
    case "degraded":
      return {
        label: "Degraded",
        dot: "bg-amber-400",
        chip: "border-amber-500/40 bg-amber-950/40 text-amber-200",
      };
    case "offline":
      return {
        label: "Offline",
        dot: "bg-rose-500",
        chip: "border-rose-500/40 bg-rose-950/35 text-rose-200",
      };
    default:
      return {
        label: "Unknown",
        dot: "bg-gray-500",
        chip: "border-surface-600 bg-surface-800 text-gray-300",
      };
  }
}

function ChannelCard({ ch }: { ch: NatsSetuMonitorChannel }) {
  const pres = statusPresentation(ch.status);
  const req = Math.max(0, ch.requests_24h);
  const err = Math.max(0, ch.errors_24h);
  const errPct = req > 0 ? Math.min(100, (err / req) * 100) : 0;

  return (
    <article
      className="rounded-xl border border-surface-700 bg-surface-900/90 p-4 flex flex-col gap-3 min-h-[180px]"
      data-testid={`nats-setu-channel-${ch.kind}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-100">{ch.label}</h3>
          <p className="text-[10px] font-mono uppercase tracking-wide text-gray-600 mt-0.5">{ch.kind}</p>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium shrink-0 ${pres.chip}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${pres.dot}`} aria-hidden />
          {pres.label}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        <div>
          <dt className="text-gray-500">Last latency</dt>
          <dd className="font-mono tabular-nums text-gray-200">
            {ch.last_latency_ms != null ? `${Math.round(ch.last_latency_ms)} ms` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">JetStream pending</dt>
          <dd className="font-mono tabular-nums text-gray-200">
            {ch.jetstream_pending != null && ch.jetstream_pending >= 0 ? ch.jetstream_pending : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">Requests (24h)</dt>
          <dd className="font-mono tabular-nums text-cyan-200/90">{req.toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Errors (24h)</dt>
          <dd className="font-mono tabular-nums text-rose-300/90">{err.toLocaleString()}</dd>
        </div>
      </dl>

      <div className="mt-auto space-y-1">
        <div className="flex justify-between text-[10px] text-gray-500">
          <span>Error rate</span>
          <span className="tabular-nums">{req > 0 ? `${errPct.toFixed(1)}%` : "—"}</span>
        </div>
        <div className="h-1.5 rounded-full bg-surface-800 overflow-hidden">
          <div
            className="h-full rounded-full bg-gradient-to-r from-amber-600/80 to-rose-500/90 transition-all duration-500"
            style={{ width: `${Math.min(100, errPct)}%` }}
          />
        </div>
        {ch.last_error ? (
          <p className="text-[11px] text-rose-300/90 leading-snug border-t border-surface-800 pt-2 mt-1">{ch.last_error}</p>
        ) : (
          <p className="text-[10px] text-gray-600 pt-1">No recent lane errors.</p>
        )}
      </div>
    </article>
  );
}

/**
 * Operations view for **NATS Setu-style** OSINT: visualize VPN/IP, email, and phone fetch lanes that publish on
 * ``setu.query`` (see ``shadow/tools/nats_lookup.py``).
 */
export default function NatsSetuMonitor() {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<NatsSetuMonitorResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const load = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true);
    else setLoading(true);
    try {
      const res = await osint.natsSetuMonitor(tenantId);
      setData(res);
      setError(null);
    } catch (e) {
      if (!silent) setData(null);
      setError(toUserFacingError(e, { subject: "NATS Setu monitor", action: "load OSINT lane status" }));
    } finally {
      if (silent) setRefreshing(false);
      else setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [autoRefresh, load]);

  const natsOk = data?.nats_connected === true;
  const jsOn = data?.jetstream_enabled === true;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="osint">NATS Setu monitor</PageTitle>
          <p className="text-sm text-gray-500 mt-1 max-w-2xl">
            Live status of external OSINT fetches routed through NATS <span className="font-mono text-gray-400">setu.query</span>{" "}
            — VPN/IP intelligence, email reputation, and phone validation responders.
          </p>
          <p className="text-xs text-gray-600 mt-2">
            <Link to="/osint" className="text-sky-400/90 hover:underline">
              ← OSINT enrichment
            </Link>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
          <span className="font-mono text-gray-400">tenant {tenantId}</span>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              className="rounded border-surface-600"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh ({Math.round(POLL_MS / 1000)}s)
          </label>
          <button
            type="button"
            disabled={loading || refreshing}
            onClick={() => void load(false)}
            className="px-3 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 text-gray-200 disabled:opacity-50 text-xs"
          >
            {loading || refreshing ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200 space-y-2">
          <p>{error}</p>
          <SupportIdHint message={error} />
        </div>
      ) : null}

      {loading && !data ? (
        <div className="flex justify-center py-24">
          <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : data ? (
        <>
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-surface-700 bg-surface-900/80 px-4 py-3">
            <span className="text-[11px] uppercase tracking-wide text-gray-500 shrink-0">Transport</span>
            <span
              className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1 text-xs font-medium ${
                natsOk
                  ? "border-emerald-500/35 bg-emerald-950/30 text-emerald-200"
                  : "border-rose-500/35 bg-rose-950/30 text-rose-200"
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${natsOk ? "bg-emerald-400" : "bg-rose-500"}`} aria-hidden />
              NATS {natsOk ? "connected" : "disconnected"}
            </span>
            <span
              className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1 text-xs font-medium ${
                jsOn
                  ? "border-cyan-500/35 bg-cyan-950/25 text-cyan-200"
                  : "border-surface-600 bg-surface-800 text-gray-400"
              }`}
            >
              JetStream {jsOn ? "on" : "off"}
            </span>
            {data.setu_query_subject ? (
              <code className="text-[11px] text-gray-400 font-mono ml-auto truncate max-w-[min(100%,14rem)]">
                subject {data.setu_query_subject}
              </code>
            ) : null}
            <Link
              to="/ops/dead-letter"
              className="text-[11px] text-brand-400 hover:text-brand-300 shrink-0 ml-2"
            >
              Dead Letter Office →
            </Link>
          </div>

          {data.nats_url_hint ? (
            <p className="text-[11px] text-gray-600 font-mono truncate" title={data.nats_url_hint}>
              Endpoint hint: {data.nats_url_hint}
            </p>
          ) : null}

          <p className="text-[11px] text-gray-500">
            Snapshot{" "}
            <span className="font-mono text-gray-400">
              {data.updated_at ? new Date(data.updated_at).toLocaleString() : "—"}
            </span>
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {(data.channels ?? []).map((ch) => (
              <ChannelCard key={ch.kind} ch={ch} />
            ))}
          </div>

          {(data.channels ?? []).length === 0 ? (
            <p className="text-sm text-gray-500 border border-dashed border-surface-700 rounded-lg px-4 py-6 text-center">
              No OSINT lanes reported — configure integration-ingress NATS Setu monitor or responders.
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
