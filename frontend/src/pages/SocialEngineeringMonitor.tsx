import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  integrations,
  type SocialEngineeringAccountRow,
  type SocialEngineeringMonitorResponse,
} from "../api/client";
import { SocialEngineeringFlag } from "../components/investigation/SocialEngineeringFlag";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

export default function SocialEngineeringMonitor(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<SocialEngineeringMonitorResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [onlyFlagged, setOnlyFlagged] = useState(true);
  const [busy, setBusy] = useState(false);
  const [highValueUsd, setHighValueUsd] = useState(5000);
  const [windowMinutes, setWindowMinutes] = useState(10);

  useRegisterPageMeta({ title: "Social engineering", subtitle: "Credential burst monitor" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrations.socialEngineeringMonitor({
        tenant_id: tenantId,
        limit: 40,
        only_flagged: onlyFlagged,
      });
      setData(res);
      setHighValueUsd(res.config.high_value_listing_usd);
      setWindowMinutes(res.config.credential_change_window_minutes);
      setError(null);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Social engineering", action: "load monitor" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId, onlyFlagged]);

  useEffect(() => {
    void load();
  }, [load]);

  const saveConfig = useCallback(async () => {
    setBusy(true);
    try {
      const res = await integrations.socialEngineeringUpdateConfig({
        tenant_id: tenantId,
        high_value_listing_usd: highValueUsd,
        credential_change_window_minutes: windowMinutes,
      });
      setData(res);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Social engineering", action: "update config" }));
    } finally {
      setBusy(false);
    }
  }, [tenantId, highValueUsd, windowMinutes]);

  const rows = useMemo(() => data?.accounts ?? [], [data]);

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="investigation">Social engineering monitor</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Flags accounts that change <strong className="text-gray-300">email</strong> and{" "}
            <strong className="text-gray-300">password</strong> within minutes of posting a{" "}
            <strong className="text-gray-300">high-value listing</strong> — a common account-takeover /
            scam listing pattern.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET /api/ingress/v1/investigation/social-engineering-monitor
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
        <p className="text-sm text-gray-500 py-16 text-center">Scanning credential timelines…</p>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <Stat label="Scanned" value={data.summary.scanned_accounts} />
            <Stat label="Flagged" value={data.summary.flagged_accounts} accent="orange" />
            <Stat label="High-value floor" value={data.summary.high_value_threshold_usd} prefix="$" />
          </div>

          {data.signals.length > 0 ? (
            <ul className="rounded-xl border border-orange-500/30 bg-orange-950/15 px-4 py-3 text-sm text-orange-100/90 space-y-1 list-disc pl-5">
              {data.signals.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          ) : null}

          <section className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 space-y-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Detection rules</h2>
            <div className="flex flex-wrap gap-4 items-end">
              <label className="text-xs text-gray-500 block min-w-[160px]">
                High-value listing (USD)
                <input
                  type="number"
                  min={500}
                  value={highValueUsd}
                  onChange={(e) => setHighValueUsd(Number(e.target.value) || 5000)}
                  className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-3 py-2 text-sm font-mono text-gray-100"
                />
              </label>
              <label className="text-xs text-gray-500 block min-w-[140px]">
                Credential window (minutes)
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={windowMinutes}
                  onChange={(e) => setWindowMinutes(Number(e.target.value) || 10)}
                  className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-3 py-2 text-sm font-mono text-gray-100"
                />
              </label>
              <label className="inline-flex items-center gap-2 text-sm text-gray-400 cursor-pointer pb-2">
                <input
                  type="checkbox"
                  checked={onlyFlagged}
                  onChange={(e) => setOnlyFlagged(e.target.checked)}
                  className="rounded border-surface-600"
                />
                Only flagged
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={() => void saveConfig()}
                className="rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white"
              >
                Save rules
              </button>
            </div>
          </section>

          <section className="rounded-xl border border-surface-700 overflow-hidden">
            <div className="px-4 py-3 border-b border-surface-700 flex justify-between items-center">
              <h2 className="text-sm font-semibold text-gray-200">Flagged accounts</h2>
              <span className="text-[11px] text-gray-500">{rows.length} rows</span>
            </div>
            <div className="divide-y divide-surface-800 max-h-[520px] overflow-y-auto">
              {rows.map((row) => (
                <AccountCard key={row.account_id} row={row} tenantId={data.tenant_id} windowMin={windowMinutes} />
              ))}
              {rows.length === 0 ? (
                <p className="text-sm text-gray-500 py-12 text-center">No accounts match this filter.</p>
              ) : null}
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
  prefix,
}: {
  label: string;
  value: number;
  accent?: string;
  prefix?: string;
}): ReactElement {
  const tone =
    accent === "orange" ? "border-orange-500/35 bg-orange-950/20" : "border-surface-700 bg-surface-900/50";
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone}`}>
      <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className="text-2xl font-bold tabular-nums text-gray-100 mt-1">
        {prefix}
        {value.toLocaleString()}
      </p>
    </div>
  );
}

function AccountCard({
  row,
  tenantId,
  windowMin,
}: {
  row: SocialEngineeringAccountRow;
  tenantId: string;
  windowMin: number;
}): ReactElement {
  return (
    <article className="px-4 py-4 hover:bg-surface-900/40">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-mono text-sm text-gray-200">{row.account_id}</p>
            <SocialEngineeringFlag
              isSocialEngineeringFlag={row.is_social_engineering_flag}
              signals={row.signals}
              minutesToEmail={row.minutes_listing_to_email_change}
              minutesToPassword={row.minutes_listing_to_password_change}
              size="md"
            />
            <span className="text-[10px] text-gray-500 tabular-nums">risk {row.risk_score}</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">{row.display_name}</p>
          <p className="text-[10px] text-gray-600 mt-0.5">
            User{" "}
            <Link
              to={`/cases?tenant=${encodeURIComponent(tenantId)}&q=${encodeURIComponent(row.user_id)}`}
              className="font-mono text-brand-400 hover:text-brand-300"
            >
              {row.user_id}
            </Link>
          </p>
        </div>
        <div className="text-right text-xs text-gray-400">
          <p className="font-semibold text-gray-200">${row.listing_value_usd.toLocaleString()}</p>
          <p className="text-[10px] mt-0.5 max-w-[200px] truncate">{row.listing_title}</p>
        </div>
      </div>

      <div className="mt-3 grid sm:grid-cols-3 gap-2 text-[11px]">
        <TimelineCell
          label="Listing posted"
          at={row.listing_posted_at}
          highlight={false}
        />
        <TimelineCell
          label="Email changed"
          at={row.email_changed_at}
          deltaMin={row.minutes_listing_to_email_change}
          windowMin={windowMin}
        />
        <TimelineCell
          label="Password changed"
          at={row.password_changed_at}
          deltaMin={row.minutes_listing_to_password_change}
          windowMin={windowMin}
        />
      </div>

      {row.signals.length > 0 ? (
        <p className="text-[9px] text-orange-300/90 mt-2 font-mono">{row.signals.join(" · ")}</p>
      ) : null}
    </article>
  );
}

function TimelineCell({
  label,
  at,
  deltaMin,
  windowMin,
  highlight,
}: {
  label: string;
  at: string | null;
  deltaMin?: number | null;
  windowMin?: number;
  highlight?: boolean;
}): ReactElement {
  const inWindow =
    deltaMin != null && windowMin != null && deltaMin >= 0 && deltaMin <= windowMin;
  return (
    <div
      className={`rounded-lg border px-2.5 py-2 ${
        inWindow || highlight
          ? "border-orange-500/40 bg-orange-950/20 text-orange-100"
          : "border-surface-700 bg-surface-900/50 text-gray-400"
      }`}
    >
      <p className="text-[9px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="font-mono text-[10px] mt-0.5">
        {at ? new Date(at).toLocaleString() : "—"}
      </p>
      {deltaMin != null ? (
        <p className="text-[10px] mt-1 tabular-nums">+{deltaMin.toFixed(1)}m after listing</p>
      ) : null}
    </div>
  );
}
