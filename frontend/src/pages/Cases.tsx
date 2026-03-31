import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { cases, type Case, type CaseCreateRequest } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import PriorityBadge from "../components/PriorityBadge";

export default function Cases() {
  const navigate = useNavigate();
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

  const fetchCases = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await cases.list({
        tenant_id: "demo",
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
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load cases");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, priorityFilter, search, sortBy]);

  useEffect(() => {
    fetchCases();
  }, [fetchCases]);

  useEffect(() => {
    (async () => {
      try {
        const [pb, views] = await Promise.all([cases.playbooks(), cases.listViews("demo")]);
        setPlaybooks(pb.playbooks || {});
        setSavedViews(views.items || []);
      } catch {
        /* ignore optional UI data failures */
      }
    })();
  }, []);

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
      await cases.bulkUpdate({ case_ids: Array.from(selectedIds), ...payload });
      setSelectedIds(new Set());
      setBulkLabel("");
      await fetchCases();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bulk action failed");
    } finally {
      setBulkBusy(false);
    }
  };

  const applyPlaybook = async (playbookId: string) => {
    if (selectedIds.size === 0) return;
    setBulkBusy(true);
    try {
      await Promise.all(Array.from(selectedIds).map((id) => cases.applyPlaybook(id, playbookId)));
      setSelectedIds(new Set());
      await fetchCases();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Playbook action failed");
    } finally {
      setBulkBusy(false);
    }
  };

  const applySavedView = async (name: string) => {
    const view = savedViews.find((v) => v.name === name);
    if (!view) return;
    const filters = view.filters || {};
    setStatusFilter(String(filters.status || ""));
    setPriorityFilter(String(filters.priority || ""));
    setSearch(String(filters.search || ""));
    setSortBy((filters.sort_by as "queue" | "updated" | "priority") || "queue");
  };

  return (
    <div className="p-6 space-y-5 animate-fade-in">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Cases</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          + New Case
        </button>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-wrap gap-3">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
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
          onChange={(e) => setPriorityFilter(e.target.value)}
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
          onChange={(e) => setSearch(e.target.value)}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 flex-1 min-w-[200px] focus:outline-none focus:ring-1 focus:ring-brand-500"
        />

        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as "queue" | "updated" | "priority")}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          <option value="queue">Queue Priority</option>
          <option value="updated">Recently Updated</option>
          <option value="priority">Priority</option>
        </select>
        <select
          onChange={(e) => {
            if (e.target.value) void applySavedView(e.target.value);
          }}
          defaultValue=""
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          <option value="">Saved Views</option>
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
          onClick={async () => {
            if (!newViewName.trim()) return;
            await cases.saveView({
              tenant_id: "demo",
              name: newViewName.trim(),
              filters: { status: statusFilter, priority: priorityFilter, search, sort_by: sortBy },
            });
            const views = await cases.listViews("demo");
            setSavedViews(views.items || []);
            setNewViewName("");
          }}
          className="px-3 py-2 bg-surface-700 hover:bg-surface-600 text-gray-200 text-sm rounded-lg"
        >
          Save View
        </button>
      </div>

      {/* Bulk Actions */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs text-gray-500">Selected: {selectedIds.size}</span>
        <button
          disabled={bulkBusy || selectedIds.size === 0}
          onClick={() => void applyBulk({ status: "investigating" })}
          className="px-3 py-1.5 bg-brand-700 hover:bg-brand-600 disabled:opacity-50 text-white text-xs rounded"
        >
          Mark Investigating
        </button>
        <button
          disabled={bulkBusy || selectedIds.size === 0}
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
          disabled={bulkBusy || selectedIds.size === 0 || !bulkLabel.trim()}
          onClick={() => void applyBulk({ add_labels: [bulkLabel.trim()] })}
          className="px-3 py-1.5 bg-surface-700 hover:bg-surface-600 disabled:opacity-50 text-gray-200 text-xs rounded"
        >
          Add Label
        </button>
        <select
          disabled={bulkBusy || selectedIds.size === 0}
          defaultValue=""
          onChange={(e) => {
            if (e.target.value) void applyPlaybook(e.target.value);
            e.currentTarget.value = "";
          }}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-xs rounded px-2 py-1"
        >
          <option value="">Run Playbook</option>
          {Object.keys(playbooks).map((id) => (
            <option key={id} value={id}>{id}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm">
          {error}
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
                </tr>
              </thead>
              <tbody>
                {caseList.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/cases/${c.id}`)}
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
                      <div className="text-[10px] text-gray-500 uppercase">
                        {c.recommended_action || "n/a"}
                      </div>
                    </td>
                  </tr>
                ))}
                {caseList.length === 0 && !loading && (
                  <tr>
                    <td
                      colSpan={9}
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

function CreateCaseModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState<CaseCreateRequest>({
    title: "",
    entity_id: "",
    tenant_id: "demo",
    trace_id: crypto.randomUUID().slice(0, 16),
    priority: "medium",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await cases.create(form);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create case");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-6 w-full max-w-lg shadow-2xl animate-fade-in">
        <h2 className="text-lg font-semibold text-gray-100 mb-4">
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
              onChange={(v) => setForm({ ...form, tenant_id: v })}
              required
            />
          </div>
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
            <p className="text-red-400 text-sm">{error}</p>
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
  const cls =
    "w-full bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500";
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required={required}
          rows={3}
          className={cls}
        />
      ) : (
        <input
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
