import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { integrations, type AutomatedBackupIndicatorsResponse, type BackupStoreIndicator } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const POLL_MS = 30_000;

type Tone = "ok" | "warn" | "stale" | "missing" | "unknown";

function statusTone(status: BackupStoreIndicator["status"]): Tone {
  if (status === "ok") return "ok";
  if (status === "warn") return "warn";
  if (status === "stale") return "stale";
  if (status === "missing") return "missing";
  return "unknown";
}

function toneBorder(t: Tone): string {
  if (t === "ok") return "border-emerald-500/45";
  if (t === "warn") return "border-amber-500/45";
  if (t === "stale" || t === "missing") return "border-rose-500/50";
  return "border-surface-600";
}

function toneLabel(t: Tone): string {
  if (t === "ok") return "Within SLA";
  if (t === "warn") return "Aging";
  if (t === "stale") return "Stale";
  if (t === "missing") return "No snapshot";
  return "Unknown";
}

function formatAge(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h ago`;
  return `${(seconds / 86400).toFixed(1)}d ago`;
}

function formatBytes(n: number | null): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function StoreCard({ store }: { store: BackupStoreIndicator }): ReactElement {
  const tone = statusTone(store.status);
  const lastLabel = store.last_snapshot_at
    ? new Date(store.last_snapshot_at).toLocaleString()
    : "Never observed";

  return (
    <article
      className={`rounded-2xl border bg-surface-900/85 p-5 flex flex-col gap-4 min-h-[220px] ${toneBorder(tone)}`}
      data-testid={`backup-store-${store.store}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-100">{store.label}</h2>
          <p className="text-[11px] font-mono uppercase tracking-wide text-gray-600 mt-0.5">{store.store}</p>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
            tone === "ok"
              ? "border-emerald-500/40 bg-emerald-950/40 text-emerald-200"
              : tone === "warn"
                ? "border-amber-500/40 bg-amber-950/35 text-amber-200"
                : tone === "stale" || tone === "missing"
                  ? "border-rose-500/40 bg-rose-950/35 text-rose-200"
                  : "border-surface-600 bg-surface-800 text-gray-400"
          }`}
        >
          {toneLabel(tone)}
        </span>
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-500">Last snapshotted</p>
        <p className="text-xl font-mono tabular-nums text-gray-100 mt-1">{lastLabel}</p>
        <p className="text-sm text-gray-500 mt-1">{formatAge(store.age_seconds)}</p>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs border-t border-surface-800 pt-3">
        <div>
          <dt className="text-gray-500">Schedule</dt>
          <dd className="text-gray-300 mt-0.5">{store.schedule_hint}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Probe source</dt>
          <dd className="font-mono text-gray-400 mt-0.5">{store.source}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-gray-500">Artifact</dt>
          <dd className="font-mono text-[11px] text-gray-400 mt-0.5 truncate" title={store.artifact_hint ?? undefined}>
            {store.artifact_hint ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-gray-500">Size</dt>
          <dd className="font-mono tabular-nums text-gray-300 mt-0.5">{formatBytes(store.size_bytes)}</dd>
        </div>
      </dl>
    </article>
  );
}

export default function AutomatedBackupIndicators(): ReactElement {
  const [data, setData] = useState<AutomatedBackupIndicatorsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useRegisterPageMeta({ title: "Automated backup", subtitle: "Postgres · JanusGraph" });

  const load = useCallback(async (silent: boolean) => {
    if (silent) setRefreshing(true);
    else setLoading(true);
    try {
      const res = await integrations.automatedBackupIndicators();
      setData(res);
      setError(null);
    } catch (e) {
      if (!silent) setData(null);
      setError(toUserFacingError(e, { subject: "Backup indicators", action: "load snapshot times" }));
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

  const postgres = data?.stores.find((s) => s.store === "postgres");
  const janus = data?.stores.find((s) => s.store === "janusgraph");

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="compliance">Automated backup</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            When <strong className="text-gray-400">PostgreSQL</strong> and{" "}
            <strong className="text-gray-400">JanusGraph</strong> were last snapshotted by the backup agent. Probes Redis
            heartbeat keys, <code className="text-gray-400">backup_status.json</code>, or newest files under the backup
            directory.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET /api/ingress/v1/ops/automated-backup-indicators
            {data?.backup_dir ? (
              <>
                {" "}
                · dir <span className="text-gray-500">{data.backup_dir}</span>
              </>
            ) : null}
            {refreshing ? <span className="text-gray-500"> · refreshing…</span> : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/ops/infra" className="text-xs text-brand-400 hover:text-brand-300 self-center">
            Infra probes →
          </Link>
          <button
            type="button"
            onClick={() => void load(true)}
            className="rounded-lg border border-surface-600 bg-surface-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-surface-700"
          >
            Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-12 text-center">Loading backup indicators…</p>
      ) : (
        <>
          {data?.thresholds_hours ? (
            <p className="text-[11px] text-gray-600">
              SLA: green ≤ {data.thresholds_hours.ok}h · amber ≤ {data.thresholds_hours.warn}h · red beyond
            </p>
          ) : null}
          <div className="grid gap-4 md:grid-cols-2">
            {postgres ? <StoreCard store={postgres} /> : null}
            {janus ? <StoreCard store={janus} /> : null}
          </div>
        </>
      )}
    </div>
  );
}
