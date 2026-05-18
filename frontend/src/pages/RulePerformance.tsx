import { useCallback, useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { analytics, type AuditEntry } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import {
  aggregateRuleOutcomes,
  filterRulesByEngine,
  inferRuleEngine,
  topByDeny,
  topByReview,
  type RuleOutcomeRow,
} from "../utils/rulePerformance";
import { toUserFacingError } from "../utils/userFacingErrors";

const CHART_TOP_N = 12;
const FETCH_LIMIT = 2500;

function rowToAuditEntry(r: unknown): AuditEntry | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Record<string, unknown>;
  if (typeof o.entity_id !== "string" || typeof o.decision !== "string") return null;
  return {
    trace_id: String(o.trace_id ?? ""),
    entity_id: o.entity_id,
    tenant_id: String(o.tenant_id ?? ""),
    event_type: String(o.event_type ?? ""),
    decision: o.decision,
    score: Number(o.score ?? 0),
    tags: Array.isArray(o.tags) ? o.tags.map(String) : [],
    rule_hits: Array.isArray(o.rule_hits) ? o.rule_hits.map(String) : [],
    created_at: String(o.created_at ?? new Date().toISOString()),
  };
}

export default function RulePerformance() {
  const { tenantId } = useTenantEnvironment();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rustOnly, setRustOnly] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await analytics.decisions({ tenant_id: tenantId, limit: FETCH_LIMIT });
      const rows = res.rows ?? [];
      const parsed = rows.map(rowToAuditEntry).filter((e): e is AuditEntry => e != null);
      setEntries(parsed);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Rule performance", action: "load decision audit" }));
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const filteredRows = useMemo(() => {
    const raw = aggregateRuleOutcomes(entries);
    return filterRulesByEngine(raw, rustOnly);
  }, [entries, rustOnly]);

  const denyChartData = useMemo(
    () =>
      topByDeny(filteredRows, CHART_TOP_N).map((r) => ({
        rule_id: r.rule_id.length > 36 ? `${r.rule_id.slice(0, 34)}…` : r.rule_id,
        full_id: r.rule_id,
        deny_count: r.deny_count,
      })),
    [filteredRows],
  );

  const reviewChartData = useMemo(
    () =>
      topByReview(filteredRows, CHART_TOP_N).map((r) => ({
        rule_id: r.rule_id.length > 36 ? `${r.rule_id.slice(0, 34)}…` : r.rule_id,
        full_id: r.rule_id,
        review_count: r.review_count,
      })),
    [filteredRows],
  );

  const totals = useMemo(() => {
    let deny = 0;
    let review = 0;
    for (const r of filteredRows) {
      deny += r.deny_count;
      review += r.review_count;
    }
    return { deny, review, rulesRepresented: filteredRows.length };
  }, [filteredRows]);

  const empty = !loading && filteredRows.length === 0;

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <PageTitle module="analytics">Rule performance</PageTitle>
        <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
          <span className="text-gray-600">Tenant: {tenantId}</span>
          <button
            type="button"
            disabled={loading}
            onClick={() => void fetchData()}
            className="px-3 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 text-gray-200 disabled:opacity-50"
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      <p className="text-sm text-gray-400 max-w-3xl leading-relaxed">
        Compare which rules drive <span className="text-rose-300 font-medium">deny</span> outcomes (fraud blocked)
        versus <span className="text-amber-300 font-medium">review</span> outcomes (analyst queue), using outcome
        attribution from audit <span className="font-mono text-gray-500">rule_hits</span>. When several rules fire on
        one decision, each listed rule receives credit for that outcome. Rust evaluator rules are detected by id
        heuristics (<span className="font-mono text-gray-500">rs_*</span>,{" "}
        <span className="font-mono text-gray-500">tarka_core::…</span>, path-like ids).
      </p>

      <div className="flex flex-wrap items-center gap-6 rounded-xl border border-surface-700 bg-surface-900/80 px-4 py-3">
        <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer select-none">
          <input
            type="checkbox"
            className="rounded border-surface-600"
            checked={rustOnly}
            onChange={(e) => setRustOnly(e.target.checked)}
          />
          Rust-style rule IDs only
        </label>
        <span className="text-xs text-gray-600">
          Uncheck to include JSON pack slugs (e.g. <span className="font-mono">velocity_guard</span>) in charts and
          table.
        </span>
      </div>

      {error ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 space-y-2">
          <p>{error}</p>
          <SupportIdHint message={error} />
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center py-24">
          <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : empty ? (
        <p className="text-sm text-gray-500 border border-surface-700 rounded-lg px-4 py-4 bg-surface-950/50">
          No rule hits in the sampled audit rows for this filter. Try widening data at the analytics sink or disable
          “Rust-style only” if pack rules are expected.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
              <div className="text-[11px] uppercase tracking-wide text-gray-500">Deny attributions</div>
              <div className="text-2xl font-semibold text-rose-300 tabular-nums">{totals.deny.toLocaleString()}</div>
              <p className="text-xs text-gray-600 mt-1">Sum over rules × outcomes (multi-fire counted)</p>
            </div>
            <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
              <div className="text-[11px] uppercase tracking-wide text-gray-500">Review attributions</div>
              <div className="text-2xl font-semibold text-amber-300 tabular-nums">
                {totals.review.toLocaleString()}
              </div>
              <p className="text-xs text-gray-600 mt-1">Rules steering toward manual review</p>
            </div>
            <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
              <div className="text-[11px] uppercase tracking-wide text-gray-500">Distinct rules</div>
              <div className="text-2xl font-semibold text-gray-200 tabular-nums">
                {totals.rulesRepresented.toLocaleString()}
              </div>
              <p className="text-xs text-gray-600 mt-1">
                From {entries.length.toLocaleString()} audit rows (limit {FETCH_LIMIT})
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            <div className="rounded-xl border border-surface-700 bg-surface-900 p-5">
              <h2 className="text-sm font-semibold text-gray-300 mb-1">Top rules — deny (fraud blocked)</h2>
              <p className="text-[11px] text-gray-600 mb-4">Highest deny attribution among {rustOnly ? "Rust-style" : "all"} rules</p>
              <ResponsiveContainer width="100%" height={Math.max(280, CHART_TOP_N * 28)}>
                <BarChart layout="vertical" data={denyChartData} margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2233" horizontal={false} />
                  <XAxis type="number" stroke="#6b7280" tick={{ fontSize: 11 }} />
                  <YAxis
                    type="category"
                    dataKey="rule_id"
                    stroke="#6b7280"
                    tick={{ fontSize: 10 }}
                    width={148}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#161923",
                      border: "1px solid #2a2f44",
                      borderRadius: 8,
                      color: "#e5e7eb",
                    }}
                    formatter={(value) => [Number(value ?? 0), "Deny"]}
                    labelFormatter={(_, payload) => {
                      const p = payload?.[0]?.payload as { full_id?: string } | undefined;
                      return p?.full_id ?? "";
                    }}
                  />
                  <Bar dataKey="deny_count" fill="#f87171" radius={[0, 4, 4, 0]} name="Deny" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="rounded-xl border border-surface-700 bg-surface-900 p-5">
              <h2 className="text-sm font-semibold text-gray-300 mb-1">Top rules — review queue</h2>
              <p className="text-[11px] text-gray-600 mb-4">Highest review attribution (noise vs deny trade)</p>
              <ResponsiveContainer width="100%" height={Math.max(280, CHART_TOP_N * 28)}>
                <BarChart layout="vertical" data={reviewChartData} margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e2233" horizontal={false} />
                  <XAxis type="number" stroke="#6b7280" tick={{ fontSize: 11 }} />
                  <YAxis
                    type="category"
                    dataKey="rule_id"
                    stroke="#6b7280"
                    tick={{ fontSize: 10 }}
                    width={148}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#161923",
                      border: "1px solid #2a2f44",
                      borderRadius: 8,
                      color: "#e5e7eb",
                    }}
                    formatter={(value) => [Number(value ?? 0), "Review"]}
                    labelFormatter={(_, payload) => {
                      const p = payload?.[0]?.payload as { full_id?: string } | undefined;
                      return p?.full_id ?? "";
                    }}
                  />
                  <Bar dataKey="review_count" fill="#fbbf24" radius={[0, 4, 4, 0]} name="Review" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-xl border border-surface-700 bg-surface-900 overflow-hidden">
            <div className="px-5 py-4 border-b border-surface-800">
              <h2 className="text-sm font-semibold text-gray-300">Full attribution table</h2>
              <p className="text-xs text-gray-600 mt-1">
                Review / (review+deny) highlights rules that mostly escalate rather than hard-stop.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wide text-gray-500 border-b border-surface-800">
                    <th className="py-3 px-4 font-medium">Rule id</th>
                    <th className="py-3 px-4 font-medium">Engine (est.)</th>
                    <th className="py-3 px-4 font-medium text-right tabular-nums">Deny</th>
                    <th className="py-3 px-4 font-medium text-right tabular-nums">Review</th>
                    <th className="py-3 px-4 font-medium text-right tabular-nums">Allow</th>
                    <th className="py-3 px-4 font-medium text-right tabular-nums">Review share</th>
                  </tr>
                </thead>
                <tbody>
                  {[...filteredRows]
                    .sort((a, b) => b.hit_decisions - a.hit_decisions)
                    .map((r) => (
                      <RuleTableRow key={r.rule_id} row={r} />
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function RuleTableRow({ row }: { row: RuleOutcomeRow }) {
  const engine = inferRuleEngine(row.rule_id);
  const denom = row.deny_count + row.review_count;
  const reviewShare = denom > 0 ? row.review_count / denom : 0;
  return (
    <tr className="border-b border-surface-800/80 hover:bg-surface-950/60">
      <td className="py-2.5 px-4 font-mono text-xs text-gray-200 align-top break-all">{row.rule_id}</td>
      <td className="py-2.5 px-4 text-xs text-gray-400 capitalize align-top">{engine}</td>
      <td className="py-2.5 px-4 text-right tabular-nums text-rose-300/90">{row.deny_count}</td>
      <td className="py-2.5 px-4 text-right tabular-nums text-amber-300/90">{row.review_count}</td>
      <td className="py-2.5 px-4 text-right tabular-nums text-gray-500">{row.allow_count}</td>
      <td className="py-2.5 px-4 text-right tabular-nums text-gray-300">
        {denom > 0 ? `${(reviewShare * 100).toFixed(1)}%` : "—"}
      </td>
    </tr>
  );
}
