import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import {
  disputes,
  type DisputeAlertState,
  type DisputeDeadlineQueueItem,
} from "../api/v1/disputes";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const ALERT_BADGE: Record<DisputeAlertState, string> = {
  breached: "bg-red-600/90 text-white",
  near_breach: "bg-amber-600/90 text-black",
  ok: "bg-emerald-700/80 text-white",
  no_deadline: "bg-surface-600 text-gray-300",
};

function formatSecondsRemaining(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds <= 0) return "0s";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatDeadline(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function DisputeDeadlineQueue() {
  const { tenantId } = useTenantEnvironment();
  const [items, setItems] = useState<DisputeDeadlineQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!tenantId.trim()) return;
    setLoading(true);
    setErr(null);
    try {
      const res = await disputes.deadlineQueue(tenantId.trim());
      setItems(res.items ?? []);
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Dispute deadlines", action: "load deadline queue" }));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const counts = useMemo(() => {
    const c = { breached: 0, near_breach: 0, ok: 0, no_deadline: 0 };
    for (const row of items) {
      c[row.alert_state] += 1;
    }
    return c;
  }, [items]);

  async function reprocess(row: DisputeDeadlineQueueItem) {
    setBusyId(row.dispute_id);
    setErr(null);
    try {
      await disputes.reprocessExternal(
        row.dispute_id,
        { tenant_id: tenantId.trim(), reason: "ops desk manual reprocess" },
        crypto.randomUUID(),
      );
      await refresh();
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "Dispute reprocess", action: "reprocess external provider" }));
    } finally {
      setBusyId(null);
    }
  }

  const canReprocess = (st: DisputeAlertState) => st === "near_breach" || st === "breached";

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6" data-testid="dispute-deadline-queue">
      <div className="space-y-1">
        <PageTitle module="disputes">Dispute deadlines</PageTitle>
        <p className="text-sm text-gray-500">
          External provider response SLA queue from{" "}
          <span className="font-mono text-xs text-gray-400">
            GET /v1/disputes/ops/deadline-queue
          </span>
          .
        </p>
      </div>

      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300 space-y-1">
          <p>{err}</p>
          <SupportIdHint
            message={err}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
          <button
            type="button"
            onClick={() => void refresh()}
            className="text-xs text-red-300/80 hover:text-red-200 underline underline-offset-2"
          >
            Retry
          </button>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <div className="text-gray-500 text-xs">Breached</div>
          <div className="text-2xl font-mono text-red-300">{loading ? "—" : counts.breached}</div>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <div className="text-gray-500 text-xs">Near breach</div>
          <div className="text-2xl font-mono text-amber-300">{loading ? "—" : counts.near_breach}</div>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <div className="text-gray-500 text-xs">OK</div>
          <div className="text-2xl font-mono text-emerald-300">{loading ? "—" : counts.ok}</div>
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm">
          <div className="text-gray-500 text-xs">No deadline</div>
          <div className="text-2xl font-mono text-gray-400">{loading ? "—" : counts.no_deadline}</div>
        </div>
      </div>

      <div className="rounded-xl border border-surface-700 bg-surface-900 overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-700 text-sm text-gray-300 flex items-center justify-between gap-3">
          <span>Queue</span>
          <button
            type="button"
            disabled={loading || !tenantId.trim()}
            onClick={() => void refresh()}
            className="px-2 py-1 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-300 disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
        {loading ? (
          <p className="p-4 text-sm text-gray-500">Loading…</p>
        ) : items.length === 0 ? (
          <p className="p-4 text-sm text-gray-500">No disputes in the external response queue.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700 text-gray-400 text-left">
                  <th className="px-4 py-3 font-medium">Dispute</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Deadline</th>
                  <th className="px-4 py-3 font-medium">Remaining</th>
                  <th className="px-4 py-3 font-medium">Alert</th>
                  <th className="px-4 py-3 font-medium">Reprocess</th>
                  <th className="px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr
                    key={row.dispute_id}
                    className="border-b border-surface-800 hover:bg-surface-800/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/disputes/${row.dispute_id}`}
                        className="font-mono text-xs text-brand-300 hover:underline"
                      >
                        {row.dispute_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-gray-300 capitalize">
                      {row.dispute_type.replace(/_/g, " ")}
                    </td>
                    <td className="px-4 py-3 text-gray-400">{row.status}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {formatDeadline(row.provider_response_deadline_at)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-300">
                      {formatSecondsRemaining(row.seconds_remaining)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        data-testid={`alert-${row.dispute_id}`}
                        className={`px-2 py-0.5 rounded text-xs ${ALERT_BADGE[row.alert_state]}`}
                      >
                        {row.alert_state.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-400">
                      {row.external_reprocess_count}
                    </td>
                    <td className="px-4 py-3">
                      {canReprocess(row.alert_state) ? (
                        <button
                          type="button"
                          data-testid={`reprocess-${row.dispute_id}`}
                          disabled={busyId === row.dispute_id}
                          onClick={() => void reprocess(row)}
                          className="px-2 py-1 text-xs rounded border border-amber-600/40 text-amber-200 hover:border-amber-400 disabled:opacity-50"
                        >
                          {busyId === row.dispute_id ? "Working…" : "Reprocess"}
                        </button>
                      ) : (
                        <span className="text-xs text-gray-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
