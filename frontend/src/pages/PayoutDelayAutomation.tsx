import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  integrations,
  type PayoutDelayPayoutRow,
  type PayoutDelayResponse,
} from "../api/client";
import { PayoutDelayHoldBadge } from "../components/integrations/PayoutDelayHoldBadge";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

function statusTone(status: string): string {
  if (status === "held") return "text-violet-300";
  if (status === "released") return "text-emerald-300";
  return "text-gray-400";
}

export default function PayoutDelayAutomation(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<PayoutDelayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [threshold, setThreshold] = useState(72);
  const [automationEnabled, setAutomationEnabled] = useState(true);

  useRegisterPageMeta({ title: "Payout delay", subtitle: "JanusGraph mule_score holds" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrations.payoutDelay({ tenant_id: tenantId });
      setData(res);
      setThreshold(res.config.mule_score_hold_threshold);
      setAutomationEnabled(res.config.automation_enabled);
      setError(null);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Payout delay", action: "load automation board" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const saveConfig = useCallback(async () => {
    setBusy(true);
    try {
      const res = await integrations.payoutDelayUpdateConfig({
        tenant_id: tenantId,
        automation_enabled: automationEnabled,
        mule_score_hold_threshold: threshold,
      });
      setData(res);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Payout delay", action: "update config" }));
    } finally {
      setBusy(false);
    }
  }, [tenantId, automationEnabled, threshold]);

  const releasePayout = useCallback(
    async (payoutId: string) => {
      setBusy(true);
      try {
        const res = await integrations.payoutDelayRelease({ tenant_id: tenantId, payout_id: payoutId });
        setData(res.board);
        setError(null);
      } catch (e) {
        setError(toUserFacingError(e, { subject: "Payout delay", action: "release hold" }));
      } finally {
        setBusy(false);
      }
    },
    [tenantId],
  );

  const heldRows = useMemo(() => (data?.payouts ?? []).filter((p) => p.status === "held"), [data]);

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="integrations">Payout delay automation</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Automatically <strong className="text-gray-300">holds outbound payouts</strong> when JanusGraph reports a
            high <span className="font-mono text-brand-300">mule_score</span> on the beneficiary entity. Analysts can
            tune the threshold or manually release holds after review.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET/PATCH /api/ingress/v1/marketplace/payout-delay · POST …/release
          </p>
        </div>
        <button
          type="button"
          disabled={loading || busy}
          onClick={() => void load()}
          className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700 disabled:opacity-50"
        >
          Refresh
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-16 text-center">Loading payout queue…</p>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Held payouts" value={data.summary.held_count} accent="violet" />
            <Stat label="Held USD" value={data.summary.held_amount_usd} decimal />
            <Stat label="Pending" value={data.summary.pending_count} />
            <Stat label="Released" value={data.summary.released_count} />
          </div>

          <section className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 space-y-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Automation config</h2>
            <div className="flex flex-wrap gap-6 items-end">
              <label className="inline-flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={automationEnabled}
                  onChange={(e) => setAutomationEnabled(e.target.checked)}
                  className="rounded border-surface-600"
                />
                Automation enabled
              </label>
              <label className="text-xs text-gray-500 block min-w-[200px]">
                Hold when mule_score ≥
                <input
                  type="number"
                  min={1}
                  max={99}
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value) || 72)}
                  className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-3 py-2 text-sm font-mono text-gray-100"
                />
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={() => void saveConfig()}
                className="rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white"
              >
                Save config
              </button>
            </div>
            <p className="text-[11px] text-gray-600">
              JanusGraph property <span className="font-mono text-gray-400">{data.config.janusgraph_property}</span> ·
              default hold {data.config.hold_duration_hours_default}h ·{" "}
              <Link to="/graph/mule-path" className="text-brand-400 hover:text-brand-300">
                Mule path explorer
              </Link>
            </p>
          </section>

          {data.events.length > 0 ? (
            <section className="rounded-xl border border-violet-500/25 bg-violet-950/10 px-4 py-3">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-violet-300/90 mb-2">
                Recent automation holds
              </h2>
              <ul className="text-xs text-gray-400 space-y-1 font-mono">
                {data.events.map((ev) => (
                  <li key={ev.event_id}>
                    {ev.timestamp.slice(0, 19)} · {ev.payout_id} · mule_score {ev.mule_score} ≥ {ev.threshold}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="rounded-xl border border-surface-700 overflow-hidden">
            <div className="px-4 py-3 border-b border-surface-700 flex justify-between items-center">
              <h2 className="text-sm font-semibold text-gray-200">Payout queue</h2>
              <span className="text-[11px] text-gray-500">{heldRows.length} held</span>
            </div>
            <div className="overflow-x-auto max-h-[480px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface-900 text-gray-500 uppercase tracking-wide">
                  <tr className="border-b border-surface-700">
                    <th className="text-left px-3 py-2">Payout</th>
                    <th className="text-right px-3 py-2">Amount</th>
                    <th className="text-right px-3 py-2">mule_score</th>
                    <th className="text-left px-3 py-2">Status</th>
                    <th className="text-right px-3 py-2">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-800 text-gray-300">
                  {data.payouts.map((row) => (
                    <PayoutRow key={row.payout_id} row={row} busy={busy} onRelease={releasePayout} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
  decimal,
}: {
  label: string;
  value: number;
  accent?: string;
  decimal?: boolean;
}): ReactElement {
  const tone =
    accent === "violet" ? "border-violet-500/35 bg-violet-950/20" : "border-surface-700 bg-surface-900/50";
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone}`}>
      <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className="text-2xl font-bold tabular-nums text-gray-100 mt-1">
        {decimal ? value.toLocaleString(undefined, { minimumFractionDigits: 2 }) : value}
      </p>
    </div>
  );
}

function PayoutRow({
  row,
  busy,
  onRelease,
}: {
  row: PayoutDelayPayoutRow;
  busy: boolean;
  onRelease: (id: string) => void;
}): ReactElement {
  return (
    <tr className="hover:bg-surface-900/40">
      <td className="px-3 py-2">
        <p className="font-mono text-gray-200">{row.payout_id}</p>
        <p className="text-[10px] text-gray-600">
          {row.beneficiary_label} · {row.entity_id} · {row.channel}
        </p>
        {row.hold_reason ? (
          <p className="text-[9px] text-violet-300/80 mt-0.5 font-mono">{row.hold_reason}</p>
        ) : null}
      </td>
      <td className="px-3 py-2 text-right tabular-nums font-semibold">
        ${row.amount_usd.toLocaleString()} {row.currency}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        <span className={row.mule_score >= 72 ? "text-rose-300 font-bold" : ""}>{row.mule_score}</span>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`capitalize font-medium ${statusTone(row.status)}`}>{row.status}</span>
          <PayoutDelayHoldBadge status={row.status} muleScore={row.mule_score} />
        </div>
      </td>
      <td className="px-3 py-2 text-right">
        {row.status === "held" ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void onRelease(row.payout_id)}
            className="text-[10px] font-semibold px-2 py-1 rounded border border-emerald-600/50 text-emerald-300 hover:bg-emerald-950/30 disabled:opacity-50"
          >
            Release
          </button>
        ) : (
          <span className="text-gray-600">—</span>
        )}
      </td>
    </tr>
  );
}
