import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { cases, type Case } from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";
import {
  buildTeamTypeWorkloadRows,
  formatHoursDuration,
  summarizeTimeToResolveByCaseType,
  teamLabel,
} from "../utils/workloadBalancerStats";

export default function WorkloadBalancer() {
  const { tenantId, setTenantId } = useTenantEnvironment();
  const [casesData, setCasesData] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await cases.list({ tenant_id: tenantId, limit: 500 });
        if (!cancelled) setCasesData(res.items ?? []);
      } catch (e) {
        if (!cancelled) {
          setCasesData([]);
          setError(toUserFacingError(e, { subject: "Cases", action: "load queue for workload metrics" }));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const byType = useMemo(() => summarizeTimeToResolveByCaseType(casesData), [casesData]);
  const teamTypeRows = useMemo(() => buildTeamTypeWorkloadRows(casesData), [casesData]);

  const openTotal = useMemo(
    () => casesData.filter((c) => c.status === "open" || c.status === "investigating").length,
    [casesData],
  );

  const teamsPresent = useMemo(() => {
    const s = new Set(casesData.map(teamLabel));
    return [...s].sort();
  }, [casesData]);

  return (
    <div className="h-full flex flex-col animate-fade-in overflow-hidden">
      <div className="shrink-0 border-b border-surface-700 px-6 py-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <PageTitle module="cases">Workload Balancer</PageTitle>
          <p className="mt-2 text-sm text-gray-500 max-w-3xl leading-relaxed">
            Team-centric queue balance with <span className="text-gray-400">time to resolve</span> (create → last update)
            by case type. Solo desks appear as a single team (assign{" "}
            <code className="text-gray-400">assigned_team</code> on cases to segment later).
          </p>
        </div>
        <label className="flex flex-col gap-1 text-xs text-gray-500 shrink-0">
          Tenant
          <input
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 font-mono min-w-[12rem]"
          />
        </label>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-6 space-y-8">
        {error ? (
          <div className="rounded-lg border border-rose-500/35 bg-rose-950/30 px-4 py-3 text-sm text-rose-200 space-y-2">
            <p>{error}</p>
            <SupportIdHint
              message={error}
              className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
              buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
            />
          </div>
        ) : null}

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <>
            <section aria-label="Queue snapshot">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="rounded-xl border border-surface-700 bg-surface-900/60 px-4 py-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Open / in flight</div>
                  <div className="text-2xl font-semibold text-gray-100 tabular-nums">{openTotal}</div>
                </div>
                <div className="rounded-xl border border-surface-700 bg-surface-900/60 px-4 py-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Teams (assigned)</div>
                  <div className="text-sm text-gray-300 mt-1">{teamsPresent.join(", ") || "—"}</div>
                </div>
                <div className="rounded-xl border border-surface-700 bg-surface-900/60 px-4 py-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Case records</div>
                  <div className="text-2xl font-semibold text-gray-100 tabular-nums">{casesData.length}</div>
                </div>
              </div>
            </section>

            <section aria-label="Time to resolve by case type">
              <h2 className="text-sm font-semibold text-gray-300 mb-3">Time to resolve — by case type</h2>
              <p className="text-[11px] text-gray-500 mb-4 leading-relaxed">
                Resolved = status <code className="text-gray-400">resolved</code> or{" "}
                <code className="text-gray-400">closed</code>. Optional field{" "}
                <code className="text-gray-400">case_type</code> overrides title inference; otherwise labels/title seed the
                type bucket.
              </p>
              {byType.length === 0 ? (
                <p className="text-sm text-gray-500 border border-dashed border-surface-600 rounded-xl px-4 py-8 text-center">
                  No resolved cases in this tenant yet — resolve or close cases to populate medians.
                </p>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  {byType.map((row) => (
                    <div
                      key={row.caseType}
                      className="rounded-xl border border-surface-700 bg-surface-900/80 px-4 py-4 space-y-2"
                    >
                      <div className="text-xs font-medium text-brand-300 truncate" title={row.caseType}>
                        {row.caseType}
                      </div>
                      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-[11px]">
                        <div>
                          <dt className="text-gray-500">Resolved</dt>
                          <dd className="text-gray-200 font-mono tabular-nums">{row.resolvedCount}</dd>
                        </div>
                        <div>
                          <dt className="text-gray-500">Median TTR</dt>
                          <dd className="text-gray-200 font-mono">{formatHoursDuration(row.medianHours)}</dd>
                        </div>
                        <div>
                          <dt className="text-gray-500">Avg TTR</dt>
                          <dd className="text-gray-200 font-mono">{formatHoursDuration(row.avgHours)}</dd>
                        </div>
                        <div>
                          <dt className="text-gray-500">P90 TTR</dt>
                          <dd className="text-gray-200 font-mono">{formatHoursDuration(row.p90Hours)}</dd>
                        </div>
                      </dl>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section aria-label="Team and case type grid">
              <h2 className="text-sm font-semibold text-gray-300 mb-3">Team × case type</h2>
              <div className="overflow-x-auto rounded-xl border border-surface-700">
                <table className="w-full text-left text-sm">
                  <thead className="bg-surface-900/95 border-b border-surface-700 text-[11px] uppercase tracking-wide text-gray-500">
                    <tr>
                      <th className="py-3 px-3 font-medium">Team</th>
                      <th className="py-3 px-3 font-medium">Case type</th>
                      <th className="py-3 px-3 font-medium text-right">Open</th>
                      <th className="py-3 px-3 font-medium text-right">Resolved</th>
                      <th className="py-3 px-3 font-medium text-right">Median TTR</th>
                      <th className="py-3 px-3 font-medium text-right">P90 TTR</th>
                    </tr>
                  </thead>
                  <tbody>
                    {teamTypeRows.map((row) => (
                      <tr key={`${row.team}-${row.caseType}`} className="border-b border-surface-800/90 hover:bg-surface-900/50">
                        <td className="py-2.5 px-3 text-gray-300">{row.team}</td>
                        <td className="py-2.5 px-3 text-gray-400">{row.caseType}</td>
                        <td className="py-2.5 px-3 text-right font-mono text-gray-300 tabular-nums">{row.openCount}</td>
                        <td className="py-2.5 px-3 text-right font-mono text-gray-300 tabular-nums">{row.resolvedCount}</td>
                        <td className="py-2.5 px-3 text-right font-mono text-gray-200 tabular-nums">
                          {formatHoursDuration(row.medianHours)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-gray-200 tabular-nums">
                          {formatHoursDuration(row.p90Hours)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {teamTypeRows.length === 0 ? (
                <p className="text-xs text-gray-600 mt-2">No rows — import cases or adjust tenant filter.</p>
              ) : null}
            </section>

            <section aria-label="Explain">
              <details className="rounded-xl border border-surface-700 bg-surface-950/40 px-4 py-3 text-[11px] text-gray-500 leading-relaxed">
                <summary className="cursor-pointer text-gray-400 font-medium">How case type is chosen</summary>
                <ul className="mt-2 list-disc pl-5 space-y-1">
                  <li>
                    API field <code className="text-gray-400">case_type</code> wins when present (future column).
                  </li>
                  <li>Otherwise titles (e.g. ATO, chargeback, scam) and the first label categorize the row.</li>
                  <li>
                    Tune buckets by setting labels or titles consistently — see{" "}
                    <Link className="text-brand-400 hover:text-brand-300" to="/cases">
                      Cases
                    </Link>
                    .
                  </li>
                </ul>
              </details>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
