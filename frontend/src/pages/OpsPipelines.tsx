import { useEffect, useMemo, useState } from "react";
import { analytics, ingest } from "../api/client";
import { PageTitle } from "../components/PageTitle";

export default function OpsPipelines() {
  const [data, setData] = useState<{
    contract_reject_by_reason: Record<string, number>;
    total_contract_rejects: number;
    since?: string;
    envelope_mode?: string;
    require_idempotency_key?: boolean;
    note?: string;
  } | null>(null);
  const [scorecard, setScorecard] = useState<{
    total_events: number;
    deny_rate_pct: number;
    top_rule_hits: Array<Record<string, unknown>>;
    per_decision: Array<{ decision: string; event_count: number; event_pct: number }>;
    window_days: number;
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [s, sc] = await Promise.all([ingest.ingestStats(), analytics.scorecard({ tenant_id: "demo", days: 7 })]);
        setData(s);
        setScorecard({
          total_events: sc.total_events,
          deny_rate_pct: sc.deny_rate_pct,
          top_rule_hits: sc.top_rule_hits ?? [],
          per_decision: (sc.per_decision ?? []).map((d) => ({
            decision: String(d.decision),
            event_count: Number(d.event_count ?? 0),
            event_pct: Number(d.event_pct ?? 0),
          })),
          window_days: sc.window_days,
        });
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Failed to load ingest stats");
      }
    })();
  }, []);

  const rows = useMemo(() => {
    const m = data?.contract_reject_by_reason ?? {};
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  }, [data]);

  const total = data?.total_contract_rejects ?? 0;

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="space-y-1">
        <PageTitle module="compliance">ETL &amp; ingest pipelines</PageTitle>
        <p className="text-sm text-gray-500">
          Contract reject counts from event-ingest (<span className="font-mono">GET /v1/ingest/stats</span>) — since
          process boot.
        </p>
      </div>

      {err && (
        <p className="text-sm text-amber-400/90">
          {err}
          <span className="block text-xs text-gray-500 mt-1">
            Dev proxy: <span className="font-mono">/api/ingest</span> → event-ingest :8007. Demo data loads when offline.
          </span>
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
          <div className="text-xs uppercase tracking-wide text-gray-500">Total contract rejects</div>
          <div className="text-3xl font-semibold tabular-nums text-gray-100 mt-1">{total}</div>
          {data?.since ? (
            <div className="text-xs text-gray-500 mt-2">
              Window: <span className="font-mono">{data.since}</span>
            </div>
          ) : null}
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm text-gray-400">
          <p>
            Prefer a server-side gateway/BFF for ingest stats in production. Avoid browser-embedded service secrets and keep{" "}
            <span className="font-mono">x-api-key</span> injection on trusted backend hops when{" "}
            <span className="font-mono">API_KEYS</span> is set on event-ingest.
          </p>
          {data && (data.envelope_mode != null || data.require_idempotency_key != null) ? (
            <p className="mt-2 text-xs text-gray-500">
              {data.envelope_mode != null ? (
                <>
                  Envelope: <span className="font-mono">{data.envelope_mode}</span>
                  {data.require_idempotency_key != null ? " · " : ""}
                </>
              ) : null}
              {data.require_idempotency_key != null ? (
                <>
                  Require idempotency key: <span className="font-mono">{String(data.require_idempotency_key)}</span>
                </>
              ) : null}
            </p>
          ) : null}
          {data?.note ? <p className="mt-2 text-xs text-gray-500">{data.note}</p> : null}
        </div>
        <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 text-sm text-gray-400">
          <div className="text-xs uppercase tracking-wide text-gray-500">Decision scorecard (analytics-sink)</div>
          <div className="text-2xl font-semibold tabular-nums text-gray-100 mt-1">
            {scorecard?.total_events ?? 0}
            <span className="text-xs text-gray-500 ml-1">events / {scorecard?.window_days ?? 7}d</span>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            Deny rate: <span className="font-mono">{(scorecard?.deny_rate_pct ?? 0).toFixed(2)}%</span>
          </p>
          <div className="mt-2 text-[11px] text-gray-500">
            {(scorecard?.per_decision ?? []).slice(0, 3).map((d) => (
              <div key={d.decision}>
                {d.decision}: <span className="font-mono text-gray-300">{d.event_count}</span> (
                <span className="font-mono text-gray-400">{d.event_pct.toFixed(1)}%</span>)
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-surface-700">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-800 text-left text-gray-400">
            <tr>
              <th className="px-3 py-2">Reason code</th>
              <th className="px-3 py-2 text-right">Count</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={2} className="px-3 py-6 text-center text-gray-500">
                  No reject reasons recorded yet — healthy stream, or counters not yet incremented.
                </td>
              </tr>
            ) : (
              rows.map(([code, n]) => (
                <tr key={code} className="border-t border-surface-700/80">
                  <td className="px-3 py-2 font-mono text-xs text-brand-300">{code}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-200">{n}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="overflow-x-auto rounded-xl border border-surface-700">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-800 text-left text-gray-400">
            <tr>
              <th className="px-3 py-2">Top rule hit</th>
              <th className="px-3 py-2 text-right">Count</th>
            </tr>
          </thead>
          <tbody>
            {(scorecard?.top_rule_hits ?? []).length === 0 ? (
              <tr>
                <td colSpan={2} className="px-3 py-6 text-center text-gray-500">
                  No scorecard rule-hit rows available.
                </td>
              </tr>
            ) : (
              (scorecard?.top_rule_hits ?? []).slice(0, 10).map((r, idx) => (
                <tr key={`${String(r.rule_id ?? idx)}`} className="border-t border-surface-700/80">
                  <td className="px-3 py-2 font-mono text-xs text-brand-300">{String(r.rule_id ?? "unknown_rule")}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-200">{Number(r.hit_count ?? 0)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-500">
        Related: <span className="font-mono">deploy/docker-compose.yml</span> event-ingest on port{" "}
        <span className="font-mono">8007</span>, analytics-sink scorecard on{" "}
        <span className="font-mono">/api/analytics/v1/analytics/scorecard</span>, and Prometheus metrics on{" "}
        <span className="font-mono">/metrics</span>.
      </p>
    </div>
  );
}
