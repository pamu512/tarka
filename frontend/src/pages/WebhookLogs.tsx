import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  integrations,
  type MarketplaceWebhookLogDetail,
  type MarketplaceWebhookLogsResponse,
} from "../api/client";
import { WebhookLogsVirtualTable } from "../components/ops/WebhookLogsVirtualTable";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const POLL_MS = 10_000;

export default function WebhookLogs(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<MarketplaceWebhookLogsResponse | null>(null);
  const [detail, setDetail] = useState<MarketplaceWebhookLogDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  useRegisterPageMeta({ title: "Webhook logs", subtitle: "Marketplace Block signals" });

  const load = useCallback(
    async (silent: boolean) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      try {
        const res = await integrations.marketplaceWebhookLogs({
          tenant_id: tenantId,
          status: statusFilter || undefined,
          signal: "block",
        });
        setData(res);
        setError(null);
        setSelectedId((prev) => {
          if (prev && res.items.some((i) => i.id === prev)) return prev;
          return res.items[0]?.id ?? null;
        });
      } catch (e) {
        if (!silent) setData(null);
        setError(toUserFacingError(e, { subject: "Webhook logs", action: "load block callbacks" }));
      } finally {
        if (silent) setRefreshing(false);
        else setLoading(false);
      }
    },
    [tenantId, statusFilter],
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

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const row = await integrations.marketplaceWebhookLogDetail(selectedId);
        if (!cancelled) setDetail(row);
      } catch {
        if (!cancelled) setDetail(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const summary = data?.summary;

  const retry = useCallback(async () => {
    if (!selectedId || detail?.status === "delivered") return;
    setRetrying(true);
    try {
      const res = await integrations.marketplaceWebhookLogRetry(selectedId);
      setDetail(res.log as MarketplaceWebhookLogDetail);
      await load(true);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Webhook", action: "retry delivery" }));
    } finally {
      setRetrying(false);
    }
  }, [selectedId, detail?.status, load]);

  const failedCount = useMemo(() => summary?.failed ?? 0, [summary]);

  return (
    <div className="p-6 flex flex-col gap-5 min-h-[calc(100vh-4rem)] animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4 max-w-6xl">
        <div>
          <PageTitle module="integrations">Webhook logs</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Outgoing <strong className="text-rose-300">Block</strong> signals POSTed to marketplace client callback
            URLs after the rule engine pins a blocking decision. Monitor delivery status, HTTP codes, and retries.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET /api/ingress/v1/marketplace/webhook-logs
            {refreshing ? " · refreshing…" : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <Link to="/settings" className="text-xs text-brand-400 hover:text-brand-300">
            SDK API keys →
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

      {summary ? (
        <div className="flex flex-wrap gap-3 max-w-3xl">
          <StatPill label="Delivered" value={summary.delivered} tone="ok" />
          <StatPill label="Failed / DLQ" value={summary.failed} tone="bad" />
          <StatPill label="Pending" value={summary.pending} tone="warn" />
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs text-gray-500 flex items-center gap-2">
          Status
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-md border border-surface-600 bg-surface-900 px-2 py-1 text-gray-200 text-xs"
          >
            <option value="">All</option>
            <option value="delivered">Delivered</option>
            <option value="failed">Failed</option>
            <option value="pending">Pending</option>
            <option value="dlq">DLQ</option>
          </select>
        </label>
        <span className="text-[11px] text-gray-600">
          Tenant <span className="font-mono text-gray-400">{tenantId}</span>
          {failedCount > 0 ? (
            <span className="text-rose-300/90"> · {failedCount} need attention</span>
          ) : null}
        </span>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200 max-w-3xl">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 gap-4 flex-col lg:flex-row">
        <div className="min-h-[320px] lg:min-h-0 flex-1 flex flex-col">
          {loading && !data ? (
            <p className="text-sm text-gray-500 py-8">Loading webhook logs…</p>
          ) : data && data.items.length === 0 ? (
            <p className="text-sm text-gray-500 py-8 rounded-xl border border-surface-700 bg-surface-900/50 px-4">
              No outgoing Block webhooks logged for this tenant yet.
            </p>
          ) : data ? (
            <WebhookLogsVirtualTable
              data={data.items}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          ) : null}
        </div>

        <aside className="w-full lg:w-[min(400px,38vw)] shrink-0 rounded-xl border border-surface-700 bg-surface-900/60 flex flex-col min-h-[240px]">
          <div className="border-b border-surface-700 px-4 py-3 flex items-start justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-gray-200">Delivery detail</h2>
              <p className="text-[11px] text-gray-500 mt-0.5">
                {selectedId ? `Log ${selectedId.slice(0, 8)}…` : "Select a row"}
              </p>
            </div>
            {detail && detail.status !== "delivered" ? (
              <button
                type="button"
                disabled={retrying}
                onClick={() => void retry()}
                className="shrink-0 rounded border border-brand-500/50 px-2 py-1 text-[11px] text-brand-200 hover:bg-brand-950/40 disabled:opacity-50"
              >
                {retrying ? "Retrying…" : "Retry"}
              </button>
            ) : null}
          </div>
          {detail ? (
            <div className="p-4 space-y-3 text-xs overflow-auto flex-1">
              <p className="font-mono text-gray-400 break-all">{detail.callback_url}</p>
              <dl className="grid grid-cols-2 gap-2 text-gray-500">
                <div>
                  <dt>HTTP</dt>
                  <dd className="text-gray-200 font-mono">{detail.http_status ?? "—"}</dd>
                </div>
                <div>
                  <dt>Latency</dt>
                  <dd className="text-gray-200 font-mono">
                    {detail.latency_ms != null ? `${detail.latency_ms} ms` : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Attempts</dt>
                  <dd className="text-gray-200 font-mono">{detail.attempt_count}</dd>
                </div>
                <div>
                  <dt>Rule</dt>
                  <dd className="text-gray-200 font-mono truncate">
                    {(detail.payload as { blocking_rule_id?: string })?.blocking_rule_id ?? "—"}
                  </dd>
                </div>
              </dl>
              {detail.last_error ? (
                <p className="text-rose-300/90 font-mono text-[11px]">{detail.last_error}</p>
              ) : null}
              <pre className="text-[11px] font-mono text-gray-400 whitespace-pre-wrap break-all border-t border-surface-800 pt-3">
                {JSON.stringify(detail.payload ?? detail.payload_preview, null, 2)}
              </pre>
              {detail.attempts && detail.attempts.length > 0 ? (
                <div className="border-t border-surface-800 pt-2">
                  <p className="text-[10px] uppercase text-gray-600 mb-1">Attempts</p>
                  <ul className="space-y-1 font-mono text-[10px] text-gray-500">
                    {detail.attempts.map((a, i) => (
                      <li key={i}>
                        #{a.attempt} {a.status_code ?? "err"} {a.latency_ms != null ? `${a.latency_ms}ms` : ""}{" "}
                        {a.error ? `— ${a.error}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : (
            <p className="p-4 text-xs text-gray-500">Select a webhook row to inspect payload and attempts.</p>
          )}
        </aside>
      </div>
    </div>
  );
}

function StatPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "ok" | "warn" | "bad";
}): ReactElement {
  const cls =
    tone === "ok"
      ? "border-emerald-500/40 text-emerald-200"
      : tone === "warn"
        ? "border-amber-500/40 text-amber-200"
        : "border-rose-500/40 text-rose-200";
  return (
    <div className={`rounded-lg border bg-surface-900/80 px-3 py-2 ${cls}`}>
      <p className="text-[10px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}
