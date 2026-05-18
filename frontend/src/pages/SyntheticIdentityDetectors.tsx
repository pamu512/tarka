import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  integrations,
  type SyntheticIdentitySignal,
  type SyntheticIdentityUserRow,
  type SyntheticIdentityDetectorsResponse,
} from "../api/client";
import { SyntheticIdentityFlag } from "../components/investigation/SyntheticIdentityFlag";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

function signalTone(risk: string): string {
  if (risk === "high") return "border-rose-500/40 text-rose-200 bg-rose-950/25";
  if (risk === "medium") return "border-amber-500/40 text-amber-200 bg-amber-950/20";
  return "border-surface-600 text-gray-400 bg-surface-900/60";
}

function SignalPill({ label, signal }: { label: string; signal: SyntheticIdentitySignal }): ReactElement {
  return (
    <div
      className={`rounded-lg border px-2.5 py-2 min-w-[140px] flex-1 ${signalTone(signal.risk)}`}
    >
      <p className="text-[9px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="text-xs font-semibold mt-0.5">{signal.label}</p>
      <p className="text-[10px] mt-1 opacity-85 leading-snug">{signal.detail}</p>
    </div>
  );
}

export default function SyntheticIdentityDetectors(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<SyntheticIdentityDetectorsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [onlyFlagged, setOnlyFlagged] = useState(true);

  useRegisterPageMeta({ title: "Synthetic identity", subtitle: "IP · browser · email" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrations.syntheticIdentityDetectors({ tenant_id: tenantId, limit: 50 });
      setData(res);
      setError(null);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Synthetic identity", action: "load detectors" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = useMemo(() => {
    const all = data?.users ?? [];
    if (!onlyFlagged) return all;
    return all.filter((u) => u.is_synthetic_identity);
  }, [data, onlyFlagged]);

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="investigation">Synthetic identity detectors</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Surfaces users whose <strong className="text-gray-300">IP</strong>,{" "}
            <strong className="text-gray-300">browser fingerprint</strong>, and{" "}
            <strong className="text-gray-300">email</strong> signals combine into high synthetic-identity risk.
            Flagged accounts show the{" "}
            <SyntheticIdentityFlag riskScore={85} isSyntheticIdentity={true} className="align-middle mx-1" />{" "}
            badge across analyst surfaces.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET /api/ingress/v1/investigation/synthetic-identity-detectors
          </p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => void load()}
          className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700 disabled:opacity-50"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-16 text-center">Scanning identity signals…</p>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Scanned" value={data.summary.scanned_users} />
            <StatCard label="Flagged" value={data.summary.flagged_users} accent="fuchsia" />
            <StatCard label="Triple high combos" value={data.summary.triple_high_combos} />
            <StatCard label="Avg risk score" value={data.summary.avg_risk_score} />
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs">
            <label className="inline-flex items-center gap-2 text-gray-400 cursor-pointer">
              <input
                type="checkbox"
                checked={onlyFlagged}
                onChange={(e) => setOnlyFlagged(e.target.checked)}
                className="rounded border-surface-600"
              />
              Only show flagged users (score ≥ {data.thresholds.flag_score})
            </label>
            <span className="text-gray-600">
              Tenant <span className="font-mono text-gray-400">{data.tenant_id}</span>
            </span>
          </div>

          <section className="rounded-xl border border-surface-700 overflow-hidden">
            <div className="px-4 py-3 border-b border-surface-700 flex justify-between items-center">
              <h2 className="text-sm font-semibold text-gray-200">Detected users</h2>
              <span className="text-[11px] text-gray-500">{rows.length} rows</span>
            </div>
            <div className="overflow-x-auto max-h-[520px] overflow-y-auto divide-y divide-surface-800">
              {rows.map((row) => (
                <UserCard key={row.user_id} row={row} tenantId={data.tenant_id} />
              ))}
              {rows.length === 0 ? (
                <p className="text-sm text-gray-500 py-12 text-center">No users match this filter.</p>
              ) : null}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: string;
}): ReactElement {
  const tone =
    accent === "fuchsia"
      ? "border-fuchsia-500/35 bg-fuchsia-950/20"
      : "border-surface-700 bg-surface-900/50";
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone}`}>
      <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className="text-2xl font-bold tabular-nums text-gray-100 mt-1">{value}</p>
    </div>
  );
}

function UserCard({ row, tenantId }: { row: SyntheticIdentityUserRow; tenantId: string }): ReactElement {
  return (
    <article className="px-4 py-4 hover:bg-surface-900/40">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-mono text-sm text-gray-200">{row.user_id}</p>
            <SyntheticIdentityFlag
              riskScore={row.risk_score}
              isSyntheticIdentity={row.is_synthetic_identity}
              comboFlags={row.combo_flags}
              size="md"
            />
            <span className="text-[10px] tabular-nums text-gray-500">score {row.risk_score}</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {row.display_name} · <span className="font-mono">{row.email}</span>
          </p>
          <p className="text-[10px] text-gray-600 mt-0.5">
            Entity{" "}
            <Link
              to={`/graph?entity=${encodeURIComponent(row.entity_id)}&tenant=${encodeURIComponent(tenantId)}`}
              className="font-mono text-brand-400 hover:text-brand-300"
            >
              {row.entity_id}
            </Link>
            · detected {new Date(row.detected_at).toLocaleString()}
          </p>
        </div>
        {row.combo_flags.length > 0 ? (
          <ul className="text-[9px] text-fuchsia-200/80 space-y-0.5 text-right max-w-xs">
            {row.combo_flags.map((f) => (
              <li key={f} className="font-mono">
                {f.replace(/_/g, " ")}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2 mt-3">
        <SignalPill label="IP" signal={row.signals.ip} />
        <SignalPill label="Browser" signal={row.signals.browser} />
        <SignalPill label="Email" signal={row.signals.email} />
      </div>
    </article>
  );
}
