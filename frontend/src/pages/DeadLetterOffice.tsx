import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  integrations,
  type NatsDeadLetterItem,
  type NatsDeadLetterOfficeResponse,
} from "../api/client";
import { DeadLetterVirtualTable } from "../components/ops/DeadLetterVirtualTable";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const POLL_MS = 12_000;

export default function DeadLetterOffice(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<NatsDeadLetterOfficeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [kindFilter, setKindFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useRegisterPageMeta({ title: "Dead Letter Office", subtitle: "NATS ingest DLQ" });

  const load = useCallback(
    async (silent: boolean) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      try {
        const res = await integrations.natsDeadLetterOffice({
          limit: 200,
          kind: kindFilter || undefined,
          tenant_id: tenantId || undefined,
        });
        setData(res);
        setError(null);
        setSelectedId((prev) => {
          if (prev && res.items.some((i) => i.id === prev)) return prev;
          return res.items[0]?.id ?? null;
        });
      } catch (e) {
        if (!silent) setData(null);
        setError(toUserFacingError(e, { subject: "Dead Letter Office", action: "peek NATS DLQ" }));
      } finally {
        if (silent) setRefreshing(false);
        else setLoading(false);
      }
    },
    [kindFilter, tenantId],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const selected: NatsDeadLetterItem | null = useMemo(() => {
    if (!data || !selectedId) return null;
    return data.items.find((i) => i.id === selectedId) ?? null;
  }, [data, selectedId]);

  const kinds = useMemo(() => {
    if (!data) return [];
    return [...new Set(data.items.map((i) => i.kind).filter(Boolean))].sort();
  }, [data]);

  return (
    <div className="p-6 flex flex-col gap-5 min-h-[calc(100vh-4rem)] animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4 max-w-6xl">
        <div>
          <PageTitle module="compliance">Dead Letter Office</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Failed ingest messages on the JetStream DLQ (<code className="text-gray-400">fraud.events.dlq</code>).
            Peeks are non-destructive (NAK) so poison payloads stay on the stream for{" "}
            <code className="text-gray-400">scripts/etl/replay_dlq.py</code>.
          </p>
          <p className="text-[11px] text-gray-600 mt-2">
            <code className="text-gray-500">GET /api/ingress/v1/ops/nats-dead-letter-office</code>
            {refreshing ? " · refreshing…" : null}
            {data?.peeked_at ? (
              <>
                {" "}
                · last peek <span className="font-mono text-gray-500">{data.peeked_at}</span>
              </>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/osint/nats-setu-monitor" className="text-xs text-brand-400 hover:text-brand-300">
            NATS Setu monitor →
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
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200 max-w-3xl">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-4xl">
        <StatCard
          label="NATS"
          value={data?.nats_connected ? "Connected" : loading ? "…" : "Offline"}
          tone={data?.nats_connected ? "ok" : "bad"}
        />
        <StatCard
          label="JetStream"
          value={data?.jetstream_enabled ? "On" : loading ? "…" : "Off"}
          tone={data?.jetstream_enabled ? "ok" : "warn"}
        />
        <StatCard
          label="Stream pending"
          value={data?.pending_estimate != null ? data.pending_estimate.toLocaleString() : "—"}
        />
        <StatCard label="DLQ subject" value={data?.dlq_subject ?? "fraud.events.dlq"} mono />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs text-gray-500 flex items-center gap-2">
          Kind
          <select
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
            className="rounded-md border border-surface-600 bg-surface-900 px-2 py-1 text-gray-200 text-xs"
          >
            <option value="">All</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
            {!kinds.includes("evaluate_4xx") ? <option value="evaluate_4xx">evaluate_4xx</option> : null}
          </select>
        </label>
        <span className="text-[11px] text-gray-600">
          Tenant filter: <span className="font-mono text-gray-400">{tenantId}</span> (from header)
        </span>
      </div>

      <div className="flex min-h-0 flex-1 gap-4 flex-col lg:flex-row">
        <div className="min-h-[320px] lg:min-h-0 flex-1 flex flex-col">
          {loading && !data ? (
            <p className="text-sm text-gray-500 py-8">Peeking DLQ…</p>
          ) : data && data.items.length === 0 ? (
            <p className="text-sm text-gray-500 py-8 rounded-xl border border-surface-700 bg-surface-900/50 px-4">
              No messages matched. Stream may be empty or filters excluded all peeked rows.
            </p>
          ) : data ? (
            <DeadLetterVirtualTable
              data={data.items}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          ) : null}
        </div>

        <aside className="w-full lg:w-[min(420px,38vw)] shrink-0 rounded-xl border border-surface-700 bg-surface-900/60 flex flex-col min-h-[240px] lg:min-h-0">
          <div className="border-b border-surface-700 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-200">Envelope</h2>
            <p className="text-[11px] text-gray-500 mt-0.5">
              {selected ? `seq ${selected.sequence} · ${selected.kind}` : "Select a row"}
            </p>
          </div>
          <pre className="flex-1 overflow-auto p-4 text-[11px] font-mono text-gray-400 leading-relaxed whitespace-pre-wrap break-all">
            {selected
              ? JSON.stringify(selected.envelope, null, 2)
              : "Click a DLQ row to inspect the full NATS payload."}
          </pre>
          {selected?.preview ? (
            <div className="border-t border-surface-700 px-4 py-2 text-[10px] text-gray-600 font-mono truncate">
              {selected.preview}
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
  mono,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "bad";
  mono?: boolean;
}): ReactElement {
  const valueCls =
    tone === "ok"
      ? "text-emerald-300"
      : tone === "warn"
        ? "text-amber-200"
        : tone === "bad"
          ? "text-rose-300"
          : "text-gray-200";
  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900/80 px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`text-sm font-medium mt-1 truncate ${valueCls} ${mono ? "font-mono text-xs" : ""}`}>{value}</p>
    </div>
  );
}
