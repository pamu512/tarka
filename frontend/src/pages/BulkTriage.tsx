import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { cases, type Case } from "../api/client";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { useToast } from "../context/ToastContext";
import { PageTitle } from "../components/PageTitle";
import StatusBadge from "../components/StatusBadge";
import PriorityBadge from "../components/PriorityBadge";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";

/** Product guardrail: bulk endpoints stay predictable for audit + UX. */
const MAX_SELECTION = 50;

export default function BulkTriage() {
  const [searchParams] = useSearchParams();
  const { tenantId, setTenantId } = useTenantEnvironment();
  const { toast } = useToast();

  const [caseRows, setCaseRows] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"" | "open" | "investigating">("open");
  const [textFilter, setTextFilter] = useState("");
  const [reviewSignalsOnly, setReviewSignalsOnly] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [resolutionComment, setResolutionComment] = useState("");
  const [resolveBusy, setResolveBusy] = useState(false);

  useEffect(() => {
    const t = searchParams.get("tenant_id")?.trim();
    if (!t) return;
    if (t !== tenantId) {
      const confirmed = window.confirm(
        `Switch workspace tenant from "${tenantId}" to "${t}" based on this link?`,
      );
      if (!confirmed) return;
    }
    setTenantId(t);
  }, [searchParams, setTenantId, tenantId]);

  const fetchCases = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await cases.list({
        tenant_id: tenantId,
        status: statusFilter || undefined,
        limit: 200,
        sort_by: "queue",
      });
      setCaseRows(resp.items);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Bulk triage", action: "load cases" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId, statusFilter]);

  useEffect(() => {
    void fetchCases();
  }, [fetchCases]);

  const filtered = useMemo(() => {
    let rows = caseRows;
    const q = textFilter.trim().toLowerCase();
    if (q) {
      rows = rows.filter((c) => {
        const ra = (c.recommended_action ?? "").toLowerCase();
        const labels = (c.labels ?? []).join(" ").toLowerCase();
        return (
          c.title.toLowerCase().includes(q) ||
          c.entity_id.toLowerCase().includes(q) ||
          ra.includes(q) ||
          labels.includes(q)
        );
      });
    }
    if (reviewSignalsOnly) {
      rows = rows.filter((c) => {
        const ra = (c.recommended_action ?? "").toLowerCase();
        return ra.includes("review") || ra.includes("manual");
      });
    }
    return rows;
  }, [caseRows, textFilter, reviewSignalsOnly]);

  const toggleRow = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        return next;
      }
      if (next.size >= MAX_SELECTION) {
        toast(`You can select at most ${MAX_SELECTION} cases per batch.`, "info");
        return prev;
      }
      next.add(id);
      return next;
    });
  };

  const selectUpToCap = () => {
    const next = new Set<string>();
    for (const c of filtered) {
      if (next.size >= MAX_SELECTION) break;
      next.add(c.id);
    }
    setSelectedIds(next);
    if (filtered.length > MAX_SELECTION) {
      toast(`Selected the first ${MAX_SELECTION} rows matching filters (cap).`, "info");
    }
  };

  const clearSelection = () => setSelectedIds(new Set());

  const applyReviewScamPreset = () => {
    setTextFilter("Review Scam");
    setReviewSignalsOnly(true);
    setStatusFilter("open");
    toast('Preset: title/search "Review Scam" + review-queue signals + open status.', "info");
  };

  const resolveSelected = async () => {
    const comment = resolutionComment.trim();
    if (selectedIds.size === 0 || !comment) return;
    setResolveBusy(true);
    try {
      const out = await cases.bulkUpdate({
        tenant_id: tenantId,
        case_ids: Array.from(selectedIds),
        status: "resolved",
        comment_body: comment,
        comment_author: "analyst",
      });
      toast(`Resolved ${out.updated} case(s) with one shared comment.`, "success");
      setSelectedIds(new Set());
      setResolutionComment("");
      await fetchCases();
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Bulk resolve", action: "update selected cases" }));
      toast(toUserFacingError(e, { subject: "Bulk resolve", action: "update selected cases" }), "error");
    } finally {
      setResolveBusy(false);
    }
  };

  const casesHref = `/cases?tenant_id=${encodeURIComponent(tenantId)}`;

  return (
    <div className="p-6 space-y-6 animate-fade-in max-w-6xl">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1 min-w-0">
          <PageTitle module="cases">Bulk triage</PageTitle>
          <p className="text-sm text-gray-500 max-w-xl">
            Select up to {MAX_SELECTION} similar cases, then resolve them together with one audit comment (stored on each
            case).
          </p>
        </div>
        <Link
          to={casesHref}
          className="text-sm font-medium px-4 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700 transition-colors shrink-0"
        >
          ← Case queue
        </Link>
      </div>

      <section className="rounded-xl border border-surface-700 bg-surface-900/80 p-4 space-y-4">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1" htmlFor="bt-status">
              Status
            </label>
            <select
              id="bt-status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
              className="bg-surface-800 border border-surface-600 text-gray-200 text-sm rounded-lg px-3 py-2 min-w-[10rem]"
            >
              <option value="">Any</option>
              <option value="open">Open</option>
              <option value="investigating">Investigating</option>
            </select>
          </div>
          <div className="flex-1 min-w-[12rem] max-w-md">
            <label className="block text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1" htmlFor="bt-search">
              Match title / entity / action / labels
            </label>
            <input
              id="bt-search"
              type="search"
              value={textFilter}
              onChange={(e) => setTextFilter(e.target.value)}
              placeholder='e.g. "Review Scam"'
              className="w-full bg-surface-800 border border-surface-600 text-gray-200 text-sm rounded-lg px-3 py-2"
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer select-none pb-2">
            <input
              type="checkbox"
              checked={reviewSignalsOnly}
              onChange={(e) => setReviewSignalsOnly(e.target.checked)}
              className="rounded border-surface-600"
            />
            Review-style queue only
          </label>
          <button
            type="button"
            onClick={applyReviewScamPreset}
            className="text-xs font-semibold px-3 py-2 rounded-lg bg-amber-500/15 text-amber-200 border border-amber-500/35 hover:bg-amber-500/25 transition-colors mb-0.5"
          >
            Preset: Review Scam
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-gray-500">
            Showing <span className="text-gray-200 tabular-nums">{filtered.length}</span> of{" "}
            <span className="text-gray-200 tabular-nums">{caseRows.length}</span> loaded
          </span>
          <button
            type="button"
            onClick={selectUpToCap}
            disabled={filtered.length === 0}
            className="text-xs font-medium px-2.5 py-1.5 rounded-md bg-surface-700 hover:bg-surface-600 disabled:opacity-40 text-gray-200"
          >
            Select first {MAX_SELECTION} matching
          </button>
          <button
            type="button"
            onClick={clearSelection}
            disabled={selectedIds.size === 0}
            className="text-xs font-medium px-2.5 py-1.5 rounded-md border border-surface-600 text-gray-400 hover:text-gray-200 disabled:opacity-40"
          >
            Clear selection
          </button>
        </div>
      </section>

      {error ? (
        <div className="rounded-lg border border-rose-500/35 bg-rose-500/10 px-3 py-2 text-sm text-rose-300 space-y-1">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
          />
        </div>
      ) : null}

      {selectedIds.size > 0 && (
        <div className="rounded-xl border border-brand-500/25 bg-brand-500/5 p-4 space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm text-gray-200">
              <span className="font-semibold text-brand-300 tabular-nums">{selectedIds.size}</span> selected
              {selectedIds.size >= MAX_SELECTION ? (
                <span className="text-amber-400/90 text-xs ml-2">(at cap)</span>
              ) : null}
            </p>
            <span className="text-xs text-gray-500">Tenant: {tenantId}</span>
          </div>
          <label className="block text-[11px] font-semibold uppercase tracking-wide text-gray-500" htmlFor="bt-comment">
            Resolution comment (applied to every selected case)
          </label>
          <textarea
            id="bt-comment"
            value={resolutionComment}
            onChange={(e) => setResolutionComment(e.target.value)}
            rows={4}
            placeholder="e.g. Confirmed template phishing — aligned with fraud ops playbook 2026-Q2; no SAR threshold."
            className="w-full bg-surface-950 border border-surface-600 text-gray-200 text-sm rounded-lg px-3 py-2 font-sans"
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={resolveBusy || !resolutionComment.trim()}
              onClick={() => void resolveSelected()}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold"
            >
              {resolveBusy ? "Resolving…" : "Resolve selected with comment"}
            </button>
            <p className="text-xs text-gray-500 self-center">
              Sets status to <span className="text-gray-400 font-mono">resolved</span> and posts the same comment on each
              case.
            </p>
          </div>
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
                  <th className="text-left py-3 px-2 w-10"></th>
                  <th className="text-left py-3 px-3 font-medium">Title</th>
                  <th className="text-left py-3 px-3 font-medium">Status</th>
                  <th className="text-left py-3 px-3 font-medium">Priority</th>
                  <th className="text-left py-3 px-3 font-medium">Recommended</th>
                  <th className="text-left py-3 px-3 font-medium">Queue</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr
                    key={c.id}
                    className={`border-b border-surface-800 hover:bg-surface-800/40 ${
                      selectedIds.has(c.id) ? "bg-brand-500/5" : ""
                    }`}
                  >
                    <td className="py-2.5 px-2">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(c.id)}
                        onChange={() => toggleRow(c.id)}
                        aria-label={`Select case ${c.id}`}
                      />
                    </td>
                    <td className="py-2.5 px-3">
                      <div className="text-gray-100 font-medium">{c.title}</div>
                      <div className="text-[11px] text-gray-500 font-mono truncate max-w-md">{c.entity_id}</div>
                    </td>
                    <td className="py-2.5 px-3">
                      <StatusBadge status={c.status} />
                    </td>
                    <td className="py-2.5 px-3">
                      <PriorityBadge priority={c.priority} />
                    </td>
                    <td className="py-2.5 px-3 text-xs text-gray-400 font-mono">{c.recommended_action ?? "—"}</td>
                    <td className="py-2.5 px-3 text-xs text-gray-300 tabular-nums">
                      {typeof c.queue_score === "number" ? c.queue_score.toFixed(0) : "—"}
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-gray-500">
                      No cases match these filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
