import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { graph, type MulePathHop, type MulePathResponse } from "../api/client";
import { MulePathDiagram } from "../components/investigation/MulePathDiagram";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

const PRESETS = [
  { id: "alice_ivan", label: "Alice → Ivan → Crypto", origin: "user_alice", mule: "mule_ivan" },
  { id: "frank_jane", label: "Frank → Jane → Wire", origin: "fraud_frank", mule: "mule_jane" },
] as const;

export default function MulePathVisualizer(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [searchParams, setSearchParams] = useSearchParams();
  const [originId, setOriginId] = useState(searchParams.get("origin") ?? "user_alice");
  const [muleId, setMuleId] = useState(searchParams.get("mule") ?? "mule_ivan");
  const [data, setData] = useState<MulePathResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedHop, setSelectedHop] = useState(0);

  useRegisterPageMeta({ title: "Mule path", subtitle: "Fund flow trace" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await graph.mulePath({
        tenant_id: tenantId,
        origin_entity_id: originId.trim() || undefined,
        mule_entity_id: muleId.trim() || undefined,
      });
      setData(res);
      setError(null);
      setSelectedHop(0);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "Mule path", action: "trace fund flow" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId, originId, muleId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const next = new URLSearchParams();
    if (originId) next.set("origin", originId);
    if (muleId) next.set("mule", muleId);
    setSearchParams(next, { replace: true });
  }, [originId, muleId, setSearchParams]);

  const hop: MulePathHop | null = data?.hops[selectedHop] ?? null;
  const currency = data?.summary.currency ?? "USD";

  const riskFlags = useMemo(() => data?.summary.risk_flags ?? [], [data]);

  return (
    <div className="p-6 flex flex-col gap-5 min-h-[calc(100vh-4rem)] max-w-6xl mx-auto animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="graph">Mule path</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            Trace the flow of funds from <strong className="text-sky-300">User A</strong> (origin) through{" "}
            <strong className="text-amber-300">User B</strong> (mule / pass-through) to an external{" "}
            <strong className="text-rose-300">Payout</strong>. Amounts and trace IDs are anchored to graph-linked
            transfers when available.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">GET /api/ingress/v1/investigation/mule-path</p>
        </div>
        <Link
          to="/graph"
          className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700 shrink-0"
        >
          Graph Explorer
        </Link>
      </div>

      <form
        className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 flex flex-wrap gap-3 items-end"
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <label className="text-xs text-gray-500 block min-w-[140px] flex-1">
          User A (origin)
          <input
            value={originId}
            onChange={(e) => setOriginId(e.target.value)}
            className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-2 py-1.5 text-sm font-mono text-gray-200"
          />
        </label>
        <label className="text-xs text-gray-500 block min-w-[140px] flex-1">
          User B (mule)
          <input
            value={muleId}
            onChange={(e) => setMuleId(e.target.value)}
            className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-2 py-1.5 text-sm font-mono text-gray-200"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setOriginId(p.origin);
                setMuleId(p.mule);
              }}
              className="text-[11px] px-2 py-1 rounded border border-surface-600 text-gray-400 hover:text-gray-200"
            >
              {p.label}
            </button>
          ))}
        </div>
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white"
        >
          {loading ? "Tracing…" : "Trace path"}
        </button>
      </form>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-12 text-center">Tracing mule path…</p>
      ) : data ? (
        <>
          <div className="flex flex-wrap gap-3">
            <StatPill label="Outflow" value={formatMoney(data.summary.total_outflow, currency)} />
            <StatPill label="Payout" value={formatMoney(data.summary.payout_amount, currency)} />
            <StatPill
              label="Mule retained"
              value={formatMoney(data.summary.mule_retained, currency)}
              tone="warn"
            />
            <StatPill label="Elapsed" value={`${data.summary.elapsed_hours}h`} />
          </div>

          {riskFlags.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {riskFlags.map((f) => (
                <span
                  key={f}
                  className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded-full border border-amber-500/35 text-amber-200/90"
                >
                  {f.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          ) : null}

          <section className="rounded-xl border border-surface-700 bg-surface-900/50 p-4">
            <MulePathDiagram
              hops={data.hops}
              transfers={data.transfers}
              currency={currency}
              selectedHopIndex={selectedHop}
              onSelectHop={setSelectedHop}
            />
          </section>

          {hop ? (
            <aside className="rounded-xl border border-surface-700 bg-surface-900/70 p-4 space-y-2 max-w-xl">
              <h2 className="text-sm font-semibold text-gray-200">Hop detail</h2>
              <p className="text-xs text-gray-500">{String(hop.description ?? "")}</p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                <dt className="text-gray-600">Role</dt>
                <dd className="font-mono text-gray-300">{hop.role}</dd>
                <dt className="text-gray-600">Entity</dt>
                <dd className="font-mono text-gray-300">{hop.entity_id}</dd>
                {hop.account_id ? (
                  <>
                    <dt className="text-gray-600">Account</dt>
                    <dd className="font-mono text-gray-300">{hop.account_id}</dd>
                  </>
                ) : null}
                {hop.referred_by ? (
                  <>
                    <dt className="text-gray-600">Referred by</dt>
                    <dd className="font-mono text-rose-300/90">{hop.referred_by}</dd>
                  </>
                ) : null}
                {hop.beneficiary ? (
                  <>
                    <dt className="text-gray-600">Beneficiary</dt>
                    <dd className="font-mono text-gray-300">{hop.beneficiary}</dd>
                  </>
                ) : null}
                {hop.channel ? (
                  <>
                    <dt className="text-gray-600">Channel</dt>
                    <dd className="font-mono text-gray-300">{hop.channel}</dd>
                  </>
                ) : null}
              </dl>
              <Link
                to={`/graph?entity=${encodeURIComponent(hop.entity_id)}`}
                className="inline-block text-xs text-brand-400 hover:text-brand-300 mt-2"
              >
                Open in Graph Explorer →
              </Link>
            </aside>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function formatMoney(amount: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency || "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

function StatPill({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "warn";
}): ReactElement {
  const cls =
    tone === "warn"
      ? "border-amber-500/35 text-amber-100"
      : "border-surface-600 text-gray-200";
  return (
    <div className={`rounded-lg border px-3 py-2 ${cls}`}>
      <p className="text-[10px] uppercase tracking-wide opacity-70">{label}</p>
      <p className="text-sm font-semibold tabular-nums">{value}</p>
    </div>
  );
}
