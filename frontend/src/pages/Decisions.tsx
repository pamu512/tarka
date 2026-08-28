import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import {
  decisions,
  toUserFacingError,
  type AuditEntry,
  type AuditRecentItem,
  type AuditRuleResult,
} from "../api/client";
import { hasDeskAnalystSession } from "../api/deskAnalystSession";
import { DegradedModeBanner } from "../components/DegradedModeBanner";
import { PageTitle } from "../components/PageTitle";
import { PackWhyStrip } from "../components/CaseView/PackWhyStrip";
import { DeviceIntegrityStrip } from "../components/CaseView/DeviceIntegrityStrip";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { packIdFromRulePackFile, resolvePackWhy } from "../utils/packWhy";
import { resolveIntegrityPresence } from "../utils/deviceIntegrity";

function formatAmount(amount: number | null, currency: string | null): string {
  if (amount == null && !currency) return "—";
  const amt = amount == null ? "—" : String(amount);
  return currency ? `${amt} ${currency}` : amt;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? d.toISOString().replace("T", " ").slice(0, 19) + "Z" : iso;
}

function RuleResultPill({ result }: { result: AuditRuleResult }) {
  const cls =
    result === "DENY"
      ? "bg-rose-500/15 text-rose-200 border-rose-500/35"
      : result === "ALLOW"
        ? "bg-emerald-500/15 text-emerald-200 border-emerald-500/35"
        : result === "SHADOW_REVIEW"
          ? "bg-violet-500/15 text-violet-200 border-violet-500/35"
          : "bg-amber-500/15 text-amber-200 border-amber-500/35";
  return (
    <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-[11px] font-semibold ${cls}`}>
      {result}
    </span>
  );
}

function compactIntegrity(row: AuditRecentItem): string {
  const view = resolveIntegrityPresence({
    integrity: row.integrity,
    tags: row.tags,
  });
  return `rooted ${view.rooted} · jailbroken ${view.jailbroken} · bio ${view.biometrics}`;
}

function compactPack(row: AuditRecentItem): string {
  return packIdFromRulePackFile(row.rule_pack_file) ?? "missing";
}

function compactRule(row: AuditRecentItem): string {
  return row.rule_hits?.length ? row.rule_hits.join(", ") : "missing";
}

function uniqueSorted(items: AuditRecentItem[], key: "event_type" | "rule_result"): string[] {
  const set = new Set<string>();
  for (const it of items) {
    const v = it[key];
    if (v) set.add(v);
  }
  return [...set].sort();
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  testId,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  testId: string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-gray-400">
      {label}
      <select
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-surface-800 border border-surface-600 rounded px-1.5 py-1 text-xs text-gray-200 focus:border-brand-500 outline-none"
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function Decisions() {
  const { tenantId } = useTenantEnvironment();
  const { traceId } = useParams<{ traceId?: string }>();
  const [items, setItems] = useState<AuditRecentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<AuditEntry | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [overrideWhy, setOverrideWhy] = useState("");
  const [overrideBusy, setOverrideBusy] = useState(false);
  const [overrideMsg, setOverrideMsg] = useState<string | null>(null);
  const analystSession = hasDeskAnalystSession();

  const [filterEventType, setFilterEventType] = useState("");
  const [filterRuleResult, setFilterRuleResult] = useState("");

  const eventTypeOptions = useMemo(() => uniqueSorted(items, "event_type"), [items]);
  const ruleResultOptions = useMemo(() => uniqueSorted(items, "rule_result"), [items]);

  const filtered = useMemo(() => {
    let rows = items;
    if (filterEventType) rows = rows.filter((r) => r.event_type === filterEventType);
    if (filterRuleResult) rows = rows.filter((r) => r.rule_result === filterRuleResult);
    return rows;
  }, [items, filterEventType, filterRuleResult]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await decisions.recentAudit(tenantId);
      setItems(res.items ?? []);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Decisions stream", action: "load recent audit" }));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!traceId) {
      setDetail(null);
      setDetailError(null);
      setDetailLoading(false);
      setOverrideWhy("");
      setOverrideMsg(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    (async () => {
      try {
        const row = await decisions.getAudit(traceId, tenantId, {
          detail_level: analystSession ? "analyst" : "minimal",
        });
        if (!cancelled) setDetail(row);
      } catch (e) {
        if (!cancelled) {
          setDetail(null);
          setDetailError(toUserFacingError(e, { subject: "Decision detail", action: "load audit" }));
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [traceId, tenantId, analystSession]);

  const packWhy = useMemo(
    () =>
      detail
        ? {
            ...resolvePackWhy({
              rule_pack_file: detail.rule_pack_file,
              rule_hits: detail.rule_hits,
              evaluate_payload: detail.evaluate_payload ?? null,
            }),
            advise: null,
          }
        : null,
    [detail],
  );

  const integrity = useMemo(
    () =>
      detail
        ? resolveIntegrityPresence({
            integrity: detail.integrity,
            tags: detail.tags,
            evaluate_payload: detail.evaluate_payload ?? null,
          })
        : null,
    [detail],
  );

  return (
    <div className="p-6 space-y-5 animate-fade-in" data-testid="decisions-queue">
      <div className="space-y-1">
        <PageTitle module="dashboard">Decisions</PageTitle>
        <p className="text-sm text-gray-500">
          Journey decision stream — progressive friction from signup through login, payment, and
          beyond. Filter by event type to isolate any step. Empty until audit/recent returns live
          rows; Tarka does not invent fixtures.
        </p>
      </div>

      <DegradedModeBanner
        error={error}
        title={error ? "Decisions stream unavailable" : undefined}
        hint={error ? "Retry the audit/recent fetch. Tarka does not show placeholder decisions." : undefined}
        onRetry={error ? () => void refresh() : undefined}
      />

      {traceId ? (
        <section
          data-testid="decisions-detail"
          className="rounded-xl border border-surface-700 bg-surface-900/50 p-4 space-y-3"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-medium text-gray-200">Audit detail</h2>
            <Link to="/decisions" className="text-xs text-brand-300 hover:underline">
              Back to stream
            </Link>
          </div>
          {detailLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="w-6 h-6 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <>
              <DegradedModeBanner
                error={detailError}
                title={detailError ? "Audit detail unavailable" : undefined}
                hint={detailError ? "Fail-closed: no invented analyst snapshot." : undefined}
              />
              {detail ? (
                <>
                {packWhy ? <PackWhyStrip {...packWhy} /> : null}
                {integrity ? <DeviceIntegrityStrip {...integrity} /> : null}
                <dl className="grid gap-2 sm:grid-cols-2 text-sm">
                  <div>
                    <dt className="text-[11px] text-gray-500">Trace</dt>
                    <dd className="font-mono text-xs text-gray-300">{detail.trace_id}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-gray-500">Decision</dt>
                    <dd className="text-gray-200">{detail.decision}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-gray-500">Score</dt>
                    <dd className="font-mono text-xs text-gray-300">{detail.score}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-gray-500">Entity</dt>
                    <dd className="font-mono text-xs text-gray-300">{detail.entity_id}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-gray-500">Created</dt>
                    <dd className="font-mono text-xs text-gray-400">{formatWhen(detail.created_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-gray-500">Rule hits</dt>
                    <dd className="font-mono text-xs text-gray-300">
                      {detail.rule_hits?.length ? detail.rule_hits.join(", ") : "—"}
                    </dd>
                  </div>
                </dl>
                {analystSession ? (
                  <form
                    data-testid="decision-override-form"
                    className="space-y-2 border-t border-surface-700 pt-3"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const why = overrideWhy.trim();
                      if (!why || !detail.trace_id || overrideBusy) return;
                      setOverrideBusy(true);
                      setOverrideMsg(null);
                      void decisions
                        .overrideDecisionLabel(tenantId, {
                          trace_id: detail.trace_id,
                          entity_id: detail.entity_id,
                          y_label: "LEGITIMATE",
                          why,
                        })
                        .then(() => {
                          setOverrideMsg(
                            "Override stored as a label for the next evaluate. Not a claim that the model learned.",
                          );
                        })
                        .catch((err) => {
                          setOverrideMsg(
                            toUserFacingError(err, {
                              subject: "Decision override",
                              action: "store label",
                            }),
                          );
                        })
                        .finally(() => setOverrideBusy(false));
                    }}
                  >
                    <p className="text-xs text-gray-400">
                      Analyst override — stores why as a label (not a CRM close). Viewer stays 403.
                    </p>
                    <textarea
                      data-testid="decision-override-why"
                      value={overrideWhy}
                      onChange={(e) => setOverrideWhy(e.target.value)}
                      rows={2}
                      placeholder="Why this FLAG/review is overridden…"
                      className="w-full rounded-md border border-surface-600 bg-surface-800 px-2 py-1.5 text-sm text-gray-100"
                    />
                    <button
                      type="submit"
                      data-testid="decision-override-submit"
                      disabled={overrideBusy || !overrideWhy.trim()}
                      className="px-2 py-1 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-300 disabled:opacity-50"
                    >
                      Store override label
                    </button>
                    {overrideMsg ? (
                      <p className="text-xs text-gray-400" data-testid="decision-override-status">
                        {overrideMsg}
                      </p>
                    ) : null}
                  </form>
                ) : null}
                </>
              ) : !detailError ? (
                <p className="text-sm text-gray-500" data-testid="decisions-detail-empty">
                  No audit row for this trace.
                </p>
              ) : null}
            </>
          )}
        </section>
      ) : null}

      <div className="bg-surface-900 border border-surface-700 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-700 text-sm text-gray-300 flex items-center justify-between gap-3 flex-wrap">
          <span>Recent decisions</span>
          <div className="flex items-center gap-3 flex-wrap">
            <FilterSelect
              label="Event type"
              value={filterEventType}
              options={eventTypeOptions}
              onChange={setFilterEventType}
              testId="filter-event-type"
            />
            <FilterSelect
              label="Rule result"
              value={filterRuleResult}
              options={ruleResultOptions}
              onChange={setFilterRuleResult}
              testId="filter-rule-result"
            />
            <button
              type="button"
              disabled={loading || !tenantId.trim()}
              onClick={() => void refresh()}
              className="px-2 py-1 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-300 disabled:opacity-50"
            >
              Refresh
            </button>
          </div>
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : filtered.length === 0 ? (
          <p className="p-6 text-sm text-gray-500" data-testid="decisions-empty">
            {items.length === 0
              ? "No recent decisions for this tenant. The stream stays empty until audit/recent returns live rows."
              : "No decisions match the current filters."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 bg-surface-800/50 border-b border-surface-700">
                  <th className="text-left py-3 px-4 font-medium">Short ID</th>
                  <th className="text-left py-3 px-4 font-medium">Event type</th>
                  <th className="text-left py-3 px-4 font-medium">Decision</th>
                  <th className="text-left py-3 px-4 font-medium">Rule result</th>
                  <th className="text-left py-3 px-4 font-medium">Pack</th>
                  <th className="text-left py-3 px-4 font-medium">Rule</th>
                  <th className="text-left py-3 px-4 font-medium">Integrity</th>
                  <th className="text-left py-3 px-4 font-medium">Amount</th>
                  <th className="text-left py-3 px-4 font-medium">Created</th>
                  <th className="text-left py-3 px-4 font-medium">Trace</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => (
                  <tr
                    key={row.trace_id}
                    data-testid={`decisions-row-${row.trace_id}`}
                    className="border-b border-surface-800 hover:bg-surface-800/50 transition-colors"
                  >
                    <td className="py-3 px-4">
                      <Link
                        to={`/decisions/${encodeURIComponent(row.trace_id)}`}
                        className="font-mono text-xs text-brand-300 hover:underline"
                      >
                        {row.short_id}
                      </Link>
                    </td>
                    <td className="py-3 px-4 text-xs text-gray-300">{row.event_type ?? "—"}</td>
                    <td className="py-3 px-4 text-xs text-gray-300">{row.decision ?? "—"}</td>
                    <td className="py-3 px-4">
                      <RuleResultPill result={row.rule_result} />
                    </td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-300">{compactPack(row)}</td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-300">{compactRule(row)}</td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-400">{compactIntegrity(row)}</td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-300">
                      {formatAmount(row.amount, row.currency)}
                    </td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-400">{formatWhen(row.created_at)}</td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-500 truncate max-w-[16rem]" title={row.trace_id}>
                      {row.trace_id}
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
