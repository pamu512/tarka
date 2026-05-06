import { useEffect, useState, useCallback, useRef, useId } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { cases, type Case, type CaseCreateRequest, type CaseDeskActivity, type CaseOpsKpis } from "../api/client";
import { useAnalystWorkspace } from "../context/AnalystWorkspaceContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { useToast } from "../context/ToastContext";
import StatusBadge from "../components/StatusBadge";
import PriorityBadge from "../components/PriorityBadge";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

function insertCaseSortedByQueue(list: Case[], row: Case): Case[] {
  const next = [...list, row];
  next.sort((a, b) => {
    const qa = typeof a.queue_score === "number" ? a.queue_score : 0;
    const qb = typeof b.queue_score === "number" ? b.queue_score : 0;
    if (qb !== qa) return qb - qa;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });
  return next;
}

export default function Cases() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { tenantId, setTenantId } = useTenantEnvironment();
  const { pinCase } = useAnalystWorkspace();
  const { toast } = useToast();
  const [caseList, setCaseList] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [sortBy, setSortBy] = useState<"queue" | "updated" | "priority">("queue");
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkLabel, setBulkLabel] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [playbooks, setPlaybooks] = useState<Record<string, Record<string, unknown>>>({});
  const [savedViews, setSavedViews] = useState<Array<{ name: string; tenant_id: string; filters: Record<string, unknown> }>>([]);
  const [newViewName, setNewViewName] = useState("");
  const [saveViewBusy, setSaveViewBusy] = useState(false);
  const [opsKpis, setOpsKpis] = useState<CaseOpsKpis | null>(null);
  const [cohort, setCohort] = useState<{
    cases_created_recent: number;
    cases_created_prior: number;
    delta_percent_vs_prior: number | null;
  } | null>(null);
  const [deskActivity, setDeskActivity] = useState<CaseDeskActivity | null>(null);
  const [savedViewSelection, setSavedViewSelection] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(true);

  useEffect(() => {
    const t = searchParams.get("tenant_id")?.trim();
    if (!t) return;
    if (t !== tenantId) {
      // Prevent silent cross-tenant context flips from shared URLs.
      const confirmed = window.confirm(
        `Switch workspace tenant from "${tenantId}" to "${t}" based on this link?`,
      );
      if (!confirmed) return;
    }
    setTenantId(t);
  }, [searchParams, setTenantId, tenantId]);

  const clearSavedViewSelection = useCallback(() => setSavedViewSelection(""), []);

  const fetchCases = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await cases.list({
        tenant_id: tenantId,
        status: statusFilter || undefined,
        limit: 100,
        sort_by: sortBy,
      });
      let data = resp.items;
      if (search) {
        const s = search.toLowerCase();
        data = data.filter(
          (c) =>
            c.title.toLowerCase().includes(s) ||
            c.entity_id.toLowerCase().includes(s),
        );
      }
      if (priorityFilter) {
        data = data.filter((c) => c.priority === priorityFilter);
      }
      setCaseList(data);
      try {
        const [kpis, coh, desk] = await Promise.all([
          cases.opsKpis(tenantId),
          cases.cohortCompare(tenantId, 7).catch(() => null),
          cases.deskActivity(tenantId, 7, 40).catch(() => null),
        ]);
        setOpsKpis(kpis);
        setCohort(
          coh
            ? {
                cases_created_recent: coh.cases_created_recent,
                cases_created_prior: coh.cases_created_prior,
                delta_percent_vs_prior: coh.delta_percent_vs_prior,
              }
            : null,
        );
        setDeskActivity(desk);
      } catch {
        setOpsKpis(null);
        setCohort(null);
        setDeskActivity(null);
      }
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Case queue", action: "load cases" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId, statusFilter, priorityFilter, search, sortBy]);

  useEffect(() => {
    fetchCases();
  }, [fetchCases]);

  useEffect(() => {
    (async () => {
      try {
        const [pb, views] = await Promise.all([cases.playbooks(), cases.listViews(tenantId)]);
        setPlaybooks(pb.playbooks || {});
        setSavedViews(views.items || []);
      } catch {
        /* ignore optional UI data failures */
      }
    })();
  }, [tenantId]);

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const applyBulk = async (payload: { status?: string; priority?: string; assigned_team?: string; add_labels?: string[] }) => {
    if (selectedIds.size === 0) return;
    setBulkBusy(true);
    try {
      await cases.bulkUpdate({ tenant_id: tenantId, case_ids: Array.from(selectedIds), ...payload });
      setSelectedIds(new Set());
      setBulkLabel("");
      await fetchCases();
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Bulk update", action: "update selected cases" }));
    } finally {
      setBulkBusy(false);
    }
  };

  const applyPlaybook = async (playbookId: string) => {
    if (selectedIds.size === 0) return;
    setBulkBusy(true);
    try {
      await Promise.all(
        Array.from(selectedIds).map((id) => cases.applyPlaybook(id, tenantId, playbookId)),
      );
      setSelectedIds(new Set());
      await fetchCases();
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Playbook apply", action: "run playbook on selected cases" }));
    } finally {
      setBulkBusy(false);
    }
  };

  /** Manual review: optimistic remove, PATCH in background, rollback + toast on failure. */
  const approveOpenCase = useCallback(
    (row: Case) => {
      let insertIndex = 0;
      setCaseList((prev) => {
        insertIndex = prev.findIndex((x) => x.id === row.id);
        if (insertIndex < 0) insertIndex = 0;
        return prev.filter((x) => x.id !== row.id);
      });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(row.id);
        return next;
      });

      void (async () => {
        try {
          const updated = await cases.update(row.id, row.tenant_id, { status: "investigating" });
          if (statusFilter !== "open") {
            setCaseList((prev) => insertCaseSortedByQueue(prev, updated));
          }
          try {
            const kpis = await cases.opsKpis(tenantId);
            setOpsKpis(kpis);
          } catch {
            /* optional */
          }
        } catch (e) {
          setCaseList((prev) => {
            const copy = [...prev];
            const at = Math.min(Math.max(0, insertIndex), copy.length);
            copy.splice(at, 0, row);
            return copy;
          });
          toast(
            toUserFacingError(e, {
              subject: "Case approval",
              action: "approve this case for investigation",
            }),
            "error",
          );
        }
      })();
    },
    [statusFilter, tenantId, toast],
  );

  const applySavedView = (name: string) => {
    const view = savedViews.find((v) => v.name === name);
    if (!view) return;
    const filters = view.filters || {};
    setSavedViewSelection(name);
    setStatusFilter(String(filters.status || ""));
    setPriorityFilter(String(filters.priority || ""));
    setSearch(String(filters.search || ""));
    setSortBy((filters.sort_by as "queue" | "updated" | "priority") || "queue");
  };

  return (
    <div className="p-6 space-y-5 animate-fade-in">
      <div className="flex items-center justify-between gap-4">
        <PageTitle module="cases">Cases</PageTitle>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          aria-haspopup="dialog"
          className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          + New Case
        </button>
      </div>

      {opsKpis && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          <KpiCard label="Total Cases" value={String(opsKpis.total_cases)} />
          <KpiCard label="Queue Avg" value={opsKpis.queue_score_avg.toFixed(1)} />
          <KpiCard label="Critical Open" value={String(opsKpis.critical_open)} />
          <KpiCard label="Investigating" value={`${(opsKpis.investigating_rate * 100).toFixed(1)}%`} />
          <KpiCard label="Resolved" value={`${(opsKpis.resolved_rate * 100).toFixed(1)}%`} />
          <KpiCard label="Median Age" value={`${opsKpis.median_case_age_hours.toFixed(1)}h`} />
          {typeof opsKpis.sla_breached_open_or_investigating === "number" ? (
            <KpiCard label="SLA breached (open)" value={String(opsKpis.sla_breached_open_or_investigating)} />
          ) : null}
          {typeof opsKpis.label_boost_cases === "number" ? (
            <KpiCard label="Label-boost queue" value={String(opsKpis.label_boost_cases)} />
          ) : null}
          {cohort && cohort.delta_percent_vs_prior != null ? (
            <KpiCard
              label="Cases vs prior 7d"
              value={`${cohort.delta_percent_vs_prior >= 0 ? "+" : ""}${cohort.delta_percent_vs_prior.toFixed(0)}%`}
            />
          ) : null}
          {deskActivity ? (
            <KpiCard label="Desk touches (7d)" value={String(deskActivity.touch_actions_total)} />
          ) : null}
        </div>
      )}

      {caseList.some((c) => c.status === "open") ? (
        <div className="rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-sm text-gray-300 space-y-1">
          <div className="font-medium text-amber-200/95">Manual review queue</div>
          <p className="text-xs text-gray-500 leading-relaxed">
            Open cases appear here for triage. Use{" "}
            <span className="text-gray-300 font-medium">Approve</span> to accept a case into investigation without
            opening the detail view — the row disappears immediately while the update runs in the background. If the
            request fails, the case is restored and an error toast explains why.
          </p>
        </div>
      ) : null}

      {deskActivity && deskActivity.touch_actions_total > 0 ? (
        <div className="rounded-xl border border-surface-700 bg-surface-900/40 p-4 space-y-3">
          <div className="text-sm font-medium text-gray-300">Case desk activity (audit)</div>
          <p className="text-xs text-gray-500">
            From <span className="font-mono">/v1/cases/ops/desk-activity</span> — analyst touches (comments, status, labels)
            in the last {deskActivity.period_days}d.
          </p>
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(deskActivity.by_action).map(([action, n]) => (
              <span
                key={action}
                className="px-2 py-0.5 rounded-md bg-surface-800 text-gray-300 font-mono"
              >
                {action}: {n}
              </span>
            ))}
          </div>
          <div className="overflow-x-auto max-h-40">
            <table className="min-w-full text-xs text-left">
              <thead className="text-gray-500 border-b border-surface-700">
                <tr>
                  <th className="py-1 pr-2">When</th>
                  <th className="py-1 pr-2">Action</th>
                  <th className="py-1 pr-2">Actor</th>
                  <th className="py-1">Case</th>
                </tr>
              </thead>
              <tbody>
                {deskActivity.recent.slice(0, 8).map((r) => (
                  <tr key={r.id} className="border-t border-surface-800">
                    <td className="py-1 pr-2 text-gray-500 whitespace-nowrap">{r.created_at ?? "—"}</td>
                    <td className="py-1 pr-2 font-mono text-brand-300/90">{r.action}</td>
                    <td className="py-1 pr-2 text-gray-400 truncate max-w-[8rem]" title={r.actor}>
                      {r.actor}
                    </td>
                    <td className="py-1 font-mono text-gray-500 truncate max-w-[10rem]">{r.resource_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {/* Filter bar — collapsible on small screens */}
      <div className="rounded-xl border border-surface-700 bg-surface-900/50 overflow-hidden">
        <button
          type="button"
          onClick={() => setFiltersOpen((o) => !o)}
          aria-expanded={filtersOpen}
          className="w-full flex items-center justify-between gap-2 px-4 py-3 text-left text-sm font-medium text-gray-300 hover:bg-surface-800/40 md:hidden"
        >
          <span>Filters &amp; saved views</span>
          <span className="text-gray-500">{filtersOpen ? "▾" : "▸"}</span>
        </button>
        <div className={`${filtersOpen ? "flex" : "hidden"} md:flex flex-wrap gap-3 p-4 pt-0 md:pt-4 border-t border-surface-800 md:border-0`}>
        <select
          value={statusFilter}
          onChange={(e) => {
            clearSavedViewSelection();
            setStatusFilter(e.target.value);
          }}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          <option value="">All Statuses</option>
          <option value="open">Open</option>
          <option value="investigating">Investigating</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Closed</option>
        </select>

        <select
          value={priorityFilter}
          onChange={(e) => {
            clearSavedViewSelection();
            setPriorityFilter(e.target.value);
          }}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          <option value="">All Priorities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        <input
          type="text"
          placeholder="Search cases..."
          value={search}
          onChange={(e) => {
            clearSavedViewSelection();
            setSearch(e.target.value);
          }}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 flex-1 min-w-[200px] focus:outline-none focus:ring-1 focus:ring-brand-500"
        />

        <select
          value={sortBy}
          onChange={(e) => {
            clearSavedViewSelection();
            setSortBy(e.target.value as "queue" | "updated" | "priority");
          }}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          <option value="queue">Queue Priority</option>
          <option value="updated">Recently Updated</option>
          <option value="priority">Priority</option>
        </select>
        <select
          value={savedViewSelection}
          onChange={(e) => {
            const v = e.target.value;
            if (v) applySavedView(v);
            else setSavedViewSelection("");
          }}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          <option value="">Saved views</option>
          {savedViews.map((v) => (
            <option key={v.name} value={v.name}>{v.name}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder="New view name"
          value={newViewName}
          onChange={(e) => setNewViewName(e.target.value)}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2"
        />
        <button
          type="button"
          disabled={saveViewBusy}
          onClick={async () => {
            if (!newViewName.trim()) return;
            setSaveViewBusy(true);
            try {
              await cases.saveView({
                tenant_id: tenantId,
                name: newViewName.trim(),
                filters: { status: statusFilter, priority: priorityFilter, search, sort_by: sortBy },
              });
              const views = await cases.listViews(tenantId);
              setSavedViews(views.items || []);
              const savedName = newViewName.trim();
              setNewViewName("");
              setSavedViewSelection(savedName);
              setError(null);
            } catch (e) {
              setError(toUserFacingError(e, { subject: "Saved view", action: "save this filter view" }));
            } finally {
              setSaveViewBusy(false);
            }
          }}
          className="px-3 py-2 bg-surface-700 hover:bg-surface-600 disabled:opacity-60 text-gray-200 text-sm rounded-lg"
        >
          {saveViewBusy ? "Saving..." : "Save View"}
        </button>
        </div>
      </div>

      {/* Bulk actions — only when something is selected */}
      {selectedIds.size > 0 && (
      <div className="flex flex-wrap gap-2 items-center rounded-lg border border-brand-500/20 bg-brand-500/5 px-3 py-2">
        <span className="text-xs text-gray-400">Selected: {selectedIds.size}</span>
        <button
          disabled={bulkBusy}
          onClick={() => void applyBulk({ status: "investigating" })}
          className="px-3 py-1.5 bg-brand-700 hover:bg-brand-600 disabled:opacity-50 text-white text-xs rounded"
        >
          Mark Investigating
        </button>
        <button
          disabled={bulkBusy}
          onClick={() => void applyBulk({ priority: "critical" })}
          className="px-3 py-1.5 bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-xs rounded"
        >
          Set Critical
        </button>
        <input
          value={bulkLabel}
          onChange={(e) => setBulkLabel(e.target.value)}
          placeholder="Add label to selected"
          className="bg-surface-800 border border-surface-600 text-gray-300 text-xs rounded px-2 py-1"
        />
        <button
          disabled={bulkBusy || !bulkLabel.trim()}
          onClick={() => void applyBulk({ add_labels: [bulkLabel.trim()] })}
          className="px-3 py-1.5 bg-surface-700 hover:bg-surface-600 disabled:opacity-50 text-gray-200 text-xs rounded"
        >
          Add Label
        </button>
        <select
          disabled={bulkBusy}
          value=""
          onChange={(e) => {
            if (e.target.value) void applyPlaybook(e.target.value);
          }}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-xs rounded px-2 py-1"
        >
          <option value="">Run Playbook</option>
          {Object.keys(playbooks).map((id) => (
            <option key={id} value={id}>{id}</option>
          ))}
        </select>
      </div>
      )}

      {/* Table */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
          <p className="mt-1 text-[11px] text-red-300/80">
            Tip: retry the queue fetch. If this persists, use Investigation in demo/mock mode and escalate service health.
          </p>
        </div>
      )}

      <div className="bg-surface-900 border border-surface-700 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 bg-surface-800/50 border-b border-surface-700">
                  <th className="text-left py-3 px-2 font-medium"></th>
                  <th className="text-left py-3 px-4 font-medium">ID</th>
                  <th className="text-left py-3 px-4 font-medium">Title</th>
                  <th className="text-left py-3 px-4 font-medium">Status</th>
                  <th className="text-left py-3 px-4 font-medium">Priority</th>
                  <th className="text-left py-3 px-4 font-medium">Entity</th>
                  <th className="text-left py-3 px-4 font-medium">Team</th>
                  <th className="text-left py-3 px-4 font-medium">Created</th>
                  <th className="text-left py-3 px-4 font-medium">Queue</th>
                  <th className="text-left py-3 px-3 font-medium w-28">Review</th>
                  <th className="text-left py-3 px-3 font-medium w-24">Open</th>
                </tr>
              </thead>
              <tbody>
                {caseList.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => {
                      pinCase({
                        caseId: c.id,
                        tenantId: c.tenant_id,
                        title: c.title || "Case",
                      });
                      navigate(
                        `/cases/${encodeURIComponent(c.id)}?tenant_id=${encodeURIComponent(c.tenant_id)}`,
                      );
                    }}
                    className="border-b border-surface-800 hover:bg-surface-800/50 cursor-pointer transition-colors"
                  >
                    <td className="py-3 px-2">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(c.id)}
                        onChange={(e) => {
                          e.stopPropagation();
                          toggleSelected(c.id);
                        }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-400">
                      {c.id.length > 8 ? c.id.slice(0, 8) + "\u2026" : c.id}
                    </td>
                    <td className="py-3 px-4 text-gray-200 font-medium">
                      {c.title}
                    </td>
                    <td className="py-3 px-4">
                      <StatusBadge status={c.status} />
                    </td>
                    <td className="py-3 px-4">
                      <PriorityBadge priority={c.priority} />
                    </td>
                    <td className="py-3 px-4 font-mono text-xs text-gray-400">
                      {c.entity_id.length > 16
                        ? c.entity_id.slice(0, 16) + "\u2026"
                        : c.entity_id}
                    </td>
                    <td className="py-3 px-4 text-gray-400">
                      {c.assigned_team || "—"}
                    </td>
                    <td className="py-3 px-4 text-gray-500 text-xs">
                      {new Date(c.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-3 px-4">
                      <div className="text-xs text-gray-300">
                        {typeof c.queue_score === "number" ? c.queue_score.toFixed(0) : "—"}
                      </div>
                      <div className="text-xs text-gray-500 uppercase">
                        {c.recommended_action || "n/a"}
                      </div>
                    </td>
                    <td className="py-3 px-3" onClick={(e) => e.stopPropagation()}>
                      {c.status === "open" ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            approveOpenCase(c);
                          }}
                          className="text-xs font-medium px-2.5 py-1 rounded-md bg-emerald-700/90 hover:bg-emerald-600 text-white transition-colors"
                        >
                          Approve
                        </button>
                      ) : (
                        <span className="text-xs text-gray-600">—</span>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <Link
                        to={`/cases/${encodeURIComponent(c.id)}?tenant_id=${encodeURIComponent(c.tenant_id)}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          pinCase({
                            caseId: c.id,
                            tenantId: c.tenant_id,
                            title: c.title || "Case",
                          });
                        }}
                        className="text-xs font-medium text-brand-400 hover:text-brand-300"
                      >
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
                {caseList.length === 0 && !loading && (
                  <tr>
                    <td
                      colSpan={11}
                      className="py-12 text-center text-gray-500"
                    >
                      No cases found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Case Modal */}
      {showCreate && (
        <CreateCaseModal
          defaultTenantId={tenantId}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            fetchCases();
          }}
        />
      )}
    </div>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-lg p-3">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className="text-sm font-semibold text-gray-200 mt-1">{value}</div>
    </div>
  );
}

function CreateCaseModal({
  defaultTenantId,
  onClose,
  onCreated,
}: {
  defaultTenantId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const tenantEditedRef = useRef(false);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const [form, setForm] = useState<CaseCreateRequest>({
    title: "",
    entity_id: "",
    tenant_id: defaultTenantId,
    trace_id: crypto.randomUUID().slice(0, 16),
    priority: "medium",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (tenantEditedRef.current) return;
    setForm((f) => ({ ...f, tenant_id: defaultTenantId }));
  }, [defaultTenantId]);

  useEffect(() => {
    previouslyFocusedRef.current = document.activeElement as HTMLElement | null;
    const el = panelRef.current?.querySelector<HTMLElement>(
      "input:not([type=hidden]), textarea, select, button",
    );
    el?.focus();
    return () => previouslyFocusedRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusables = panel.querySelectorAll<HTMLElement>(
        "a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const description = (form.description ?? "").trim();
      const assignedTeam = (form.assigned_team ?? "").trim();
      const createPayload = {
        tenant_id: form.tenant_id,
        entity_id: form.entity_id,
        trace_id: form.trace_id,
        title: form.title,
        priority: form.priority,
      };
      const created = await cases.create(createPayload);
      const tenant = created.tenant_id || createPayload.tenant_id;

      // Keep "Team" and "Description" inputs truthful even though create API does not natively persist them.
      const followUps: Array<Promise<unknown>> = [];
      if (assignedTeam) {
        followUps.push(
          cases
            .update(created.id, tenant, { assigned_team: assignedTeam })
            .catch(() => null),
        );
      }
      if (description) {
        followUps.push(
          cases
            .addComment(created.id, tenant, "analyst", description)
            .catch(() => null),
        );
      }
      if (followUps.length > 0) await Promise.all(followUps);
      onCreated();
    } catch (err) {
      setError(toUserFacingError(err, { subject: "Case creation", action: "create a new case" }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-case-title"
        onClick={(e) => e.stopPropagation()}
        className="bg-surface-900 border border-surface-700 rounded-xl p-6 w-full max-w-lg shadow-2xl animate-fade-in"
      >
        <h2 id="create-case-title" className="text-lg font-semibold text-gray-100 mb-4">
          New Case
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Field
            label="Title"
            value={form.title}
            onChange={(v) => setForm({ ...form, title: v })}
            required
          />
          <Field
            label="Description"
            value={form.description ?? ""}
            onChange={(v) => setForm({ ...form, description: v })}
            multiline
          />
          <div className="grid grid-cols-2 gap-4">
            <Field
              label="Entity ID"
              value={form.entity_id}
              onChange={(v) => setForm({ ...form, entity_id: v })}
              required
            />
            <Field
              label="Tenant ID"
              value={form.tenant_id}
              onChange={(v) => {
                tenantEditedRef.current = true;
                setForm({ ...form, tenant_id: v });
              }}
              required
            />
          </div>
          <Field
            label="Trace ID"
            value={form.trace_id}
            onChange={(v) => setForm({ ...form, trace_id: v })}
            required
          />
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">
                Priority
              </label>
              <select
                value={form.priority}
                onChange={(e) =>
                  setForm({ ...form, priority: e.target.value })
                }
                className="w-full bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
            <Field
              label="Team"
              value={form.assigned_team ?? ""}
              onChange={(v) => setForm({ ...form, assigned_team: v })}
            />
          </div>

          {error && (
            <div className="text-red-400 text-sm space-y-1">
              <p>{error}</p>
              <SupportIdHint
                message={error}
                className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
                buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
              />
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {submitting ? "Creating..." : "Create Case"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  required,
  multiline,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  multiline?: boolean;
}) {
  const id = useId();
  const cls =
    "w-full bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500";
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-gray-400 mb-1">
        {label}
      </label>
      {multiline ? (
        <textarea
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required={required}
          rows={3}
          className={cls}
        />
      ) : (
        <input
          id={id}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required={required}
          className={cls}
        />
      )}
    </div>
  );
}
