import type { ComponentType, SVGProps } from "react";
import { useCallback, useEffect, useState } from "react";
import { entityLists, type ListEntryData } from "../api/client";
import { ModuleIcon } from "../components/ModuleIcon";
import { PageTitle } from "../components/PageTitle";

const TENANT = "demo";
type ListType = "whitelist" | "blacklist" | "test_bypass";

function iconBase(className?: string) {
  return `shrink-0 ${className ?? "w-5 h-5"}`;
}

/** Stroke icons aligned with ModuleIcon (24px, 1.75 stroke). */
function IconListWhitelist(p: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...p}
      className={iconBase(p.className)}
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12l2.5 2.5L16 9" />
    </svg>
  );
}

function IconListBlacklist(p: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...p}
      className={iconBase(p.className)}
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </svg>
  );
}

function IconListTestBypass(p: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...p}
      className={iconBase(p.className)}
    >
      <circle cx="12" cy="12" r="9" strokeDasharray="3 2.5" />
      <path d="M8 12l2 2 4-4" />
    </svg>
  );
}

function IconSearch(p: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...p}
      className={iconBase(p.className)}
    >
      <circle cx="11" cy="11" r="6" />
      <path d="M20 20l-3.5-3.5" />
    </svg>
  );
}

function IconTrash(p: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...p}
      className={iconBase(p.className ?? "w-3.5 h-3.5")}
    >
      <path d="M3 6h18M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6M10 11v6M14 11v6" />
    </svg>
  );
}

const LIST_ICONS: Record<ListType, ComponentType<SVGProps<SVGSVGElement>>> = {
  whitelist: IconListWhitelist,
  blacklist: IconListBlacklist,
  test_bypass: IconListTestBypass,
};

const LIST_ACCENTS: Record<
  ListType,
  { ring: string; iconWrap: string; tabActive: string; dot: string }
> = {
  whitelist: {
    ring: "ring-emerald-500/25",
    iconWrap: "border-emerald-500/35 bg-emerald-500/10 text-emerald-400",
    tabActive: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
    dot: "bg-emerald-400",
  },
  blacklist: {
    ring: "ring-red-500/25",
    iconWrap: "border-red-500/35 bg-red-500/10 text-red-400",
    tabActive: "bg-red-500/15 text-red-300 border-red-500/40",
    dot: "bg-red-400",
  },
  test_bypass: {
    ring: "ring-violet-500/25",
    iconWrap: "border-violet-500/35 bg-violet-500/10 text-violet-400",
    tabActive: "bg-violet-500/15 text-violet-300 border-violet-500/40",
    dot: "bg-violet-400",
  },
};

const LIST_META: Record<ListType, { label: string; description: string }> = {
  whitelist: {
    label: "Whitelist",
    description: "Entities that always receive ALLOW decisions from the decision pipeline.",
  },
  blacklist: {
    label: "Blacklist",
    description: "Entities that always receive DENY decisions — hard stops for known fraud.",
  },
  test_bypass: {
    label: "Test bypass",
    description: "Full evaluation runs, but the final decision is overridden to ALLOW for safe testing.",
  },
};

export default function EntityLists() {
  const [activeTab, setActiveTab] = useState<ListType>("whitelist");
  const [entries, setEntries] = useState<ListEntryData[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [checkEntity, setCheckEntity] = useState("");
  const [checkResult, setCheckResult] = useState<{
    found: boolean;
    list_type: string | null;
    action: string;
    reason: string;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [listRes, statsRes] = await Promise.all([
        entityLists.list(activeTab, TENANT),
        entityLists.stats(TENANT),
      ]);
      setEntries(listRes.entries);
      setStats(statsRes.stats);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [activeTab]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRemove = async (entityId: string) => {
    if (!confirm(`Remove ${entityId} from ${LIST_META[activeTab].label}?`)) return;
    try {
      await entityLists.remove(activeTab, TENANT, entityId);
      void load();
    } catch (e) {
      console.error(e);
    }
  };

  const handleCheck = async () => {
    if (!checkEntity.trim()) return;
    try {
      const result = await entityLists.check(TENANT, checkEntity.trim());
      setCheckResult(result);
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 animate-fade-in pb-16">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <PageTitle module="entity-lists">Entity lists</PageTitle>
          <p className="text-sm text-gray-500 -mt-2 max-w-2xl">
            Allowlist, blocklist, and test-bypass entries feed the decision API. Counts update per list; use quick check
            to see how an entity would resolve.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="shrink-0 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors shadow-sm shadow-brand-900/20"
        >
          <span className="text-lg leading-none font-light" aria-hidden>
            +
          </span>
          Add entry
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {(Object.keys(LIST_META) as ListType[]).map((lt) => {
          const Icon = LIST_ICONS[lt];
          const acc = LIST_ACCENTS[lt];
          return (
            <button
              key={lt}
              type="button"
              onClick={() => setActiveTab(lt)}
              className={`text-left rounded-xl border border-surface-700 bg-surface-900 p-4 flex items-center gap-4 transition-all hover:border-surface-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50 ${activeTab === lt ? `ring-2 ${acc.ring} border-surface-600` : ""}`}
            >
              <div
                className={`flex h-11 w-11 items-center justify-center rounded-xl border ${acc.iconWrap}`}
                aria-hidden
              >
                <Icon className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{LIST_META[lt].label}</div>
                <div className="text-2xl font-semibold text-gray-100 tabular-nums">{stats[lt] ?? 0}</div>
              </div>
            </button>
          );
        })}
      </div>

      <div className="rounded-xl border border-surface-700 bg-surface-900/80 p-4 sm:p-5 space-y-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-200">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-surface-600 bg-surface-800 text-brand-400">
            <IconSearch className="w-4 h-4" />
          </span>
          Quick entity check
        </div>
        <p className="text-xs text-gray-500">Resolve list membership and recommended action for a single entity ID.</p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            value={checkEntity}
            onChange={(e) => setCheckEntity(e.target.value)}
            placeholder="Entity ID…"
            className="flex-1 bg-surface-950 border border-surface-600 rounded-xl px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-brand-500/50"
            onKeyDown={(e) => e.key === "Enter" && void handleCheck()}
          />
          <button
            type="button"
            onClick={() => void handleCheck()}
            className="px-5 py-2.5 rounded-xl bg-surface-700 hover:bg-surface-600 border border-surface-600 text-gray-200 text-sm font-medium transition-colors"
          >
            Check
          </button>
        </div>
        {checkResult && (
          <div
            className={`rounded-xl border px-4 py-3 text-sm flex items-start gap-3 ${
              checkResult.found
                ? checkResult.action === "deny"
                  ? "border-red-500/35 bg-red-500/10 text-red-200"
                  : "border-emerald-500/35 bg-emerald-500/10 text-emerald-200"
                : "border-surface-600 bg-surface-950/80 text-gray-400"
            }`}
          >
            {checkResult.found ? (
              <>
                <span
                  className={`mt-1 h-2 w-2 rounded-full shrink-0 ${checkResult.action === "deny" ? "bg-red-400" : "bg-emerald-400"}`}
                />
                <div>
                  <div className="font-medium text-gray-100">
                    On <span className="text-white">{checkResult.list_type}</span> · action{" "}
                    <span className="font-mono text-xs uppercase">{checkResult.action}</span>
                  </div>
                  <div className="text-xs mt-1 opacity-90">{checkResult.reason}</div>
                </div>
              </>
            ) : (
              <>
                <span className="mt-1 h-2 w-2 rounded-full shrink-0 bg-gray-500" />
                <span>Not found on any configured list for this tenant.</span>
              </>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <div className="inline-flex flex-wrap gap-1.5 rounded-xl border border-surface-700 bg-surface-900/60 p-1.5 w-fit max-w-full">
          {(Object.keys(LIST_META) as ListType[]).map((lt) => {
            const Icon = LIST_ICONS[lt];
            const acc = LIST_ACCENTS[lt];
            const active = activeTab === lt;
            return (
              <button
                key={lt}
                type="button"
                onClick={() => setActiveTab(lt)}
                className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors border ${
                  active
                    ? acc.tabActive
                    : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-surface-800/80"
                }`}
              >
                <Icon className={`w-4 h-4 ${active ? "" : "opacity-80"}`} />
                {LIST_META[lt].label}
                <span
                  className={`tabular-nums text-xs px-1.5 py-0.5 rounded-md ${active ? "bg-black/20" : "bg-surface-800 text-gray-500"}`}
                >
                  {stats[lt] ?? 0}
                </span>
              </button>
            );
          })}
        </div>
        <p className="text-xs text-gray-500 flex items-start gap-2">
          <span className={`mt-1.5 h-1.5 w-1.5 rounded-full shrink-0 ${LIST_ACCENTS[activeTab].dot}`} />
          {LIST_META[activeTab].description}
        </p>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-500">
          <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">Loading entries…</span>
        </div>
      ) : entries.length === 0 ? (
        <div className="rounded-xl border border-dashed border-surface-600 bg-surface-900/40 px-6 py-16 text-center">
          <ModuleIcon module="entity-lists" className="w-12 h-12 text-gray-600 mx-auto mb-3" aria-hidden />
          <div className="text-sm font-medium text-gray-300">No entries in {LIST_META[activeTab].label}</div>
          <p className="text-xs text-gray-600 mt-1 max-w-sm mx-auto">
            Add an entity from the button above. Entries apply to tenant <code className="text-gray-500">{TENANT}</code>.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-surface-700 overflow-hidden bg-surface-900">
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="border-b border-surface-700 text-left text-xs text-gray-500 uppercase tracking-wide bg-surface-900/95">
                  <th className="px-4 py-3 font-semibold">Entity ID</th>
                  <th className="px-4 py-3 font-semibold">Reason</th>
                  <th className="px-4 py-3 font-semibold">Created by</th>
                  <th className="px-4 py-3 font-semibold">Expires</th>
                  <th className="px-4 py-3 font-semibold">Created</th>
                  <th className="px-4 py-3 font-semibold w-28">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-800">
                {entries.map((e) => (
                  <tr key={e.entity_id} className="text-gray-300 hover:bg-surface-800/40 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-brand-200/90">{e.entity_id}</td>
                    <td className="px-4 py-3 text-gray-400 max-w-[200px] truncate" title={e.reason || undefined}>
                      {e.reason || "—"}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{e.created_by}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                      {e.expires_at ? new Date(e.expires_at).toLocaleDateString() : "Never"}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                      {new Date(e.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => void handleRemove(e.entity_id)}
                        className="inline-flex items-center gap-1.5 text-xs font-medium text-red-400/90 hover:text-red-300 transition-colors"
                      >
                        <IconTrash />
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showAdd ? (
        <AddEntryModal initialListType={activeTab} onClose={() => setShowAdd(false)} onAdded={load} />
      ) : null}
    </div>
  );
}

function AddEntryModal({
  initialListType,
  onClose,
  onAdded,
}: {
  initialListType: ListType;
  onClose: () => void;
  onAdded: () => void | Promise<void>;
}) {
  const [targetList, setTargetList] = useState<ListType>(initialListType);
  const [form, setForm] = useState({ entity_id: "", reason: "", created_by: "admin", expires_at: "" });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setTargetList(initialListType);
  }, [initialListType]);

  const Icon = LIST_ICONS[targetList];
  const acc = LIST_ACCENTS[targetList];

  const submit = async () => {
    if (!form.entity_id.trim()) return;
    setSubmitting(true);
    try {
      await entityLists.add(targetList, {
        tenant_id: TENANT,
        entity_id: form.entity_id.trim(),
        reason: form.reason,
        created_by: form.created_by,
        expires_at: form.expires_at || null,
      });
      await onAdded();
      onClose();
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-[2px]"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-surface-700 bg-surface-900 shadow-xl shadow-black/40"
        role="dialog"
        aria-labelledby="add-entry-title"
        aria-describedby="add-entry-list-hint"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 pt-5 pb-4 border-b border-surface-700">
          <div className="flex items-start gap-3">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${acc.iconWrap}`}>
              <Icon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <h2 id="add-entry-title" className="text-lg font-semibold text-gray-100">
                Add list entry
              </h2>
              <p id="add-entry-list-hint" className="text-xs text-gray-500 mt-0.5">
                Choose which list receives this entity. You can switch lists without closing the form.
              </p>
            </div>
          </div>
          <div
            className="mt-4 flex flex-wrap gap-1.5 rounded-xl border border-surface-700 bg-surface-950/60 p-1.5"
            role="tablist"
            aria-label="Target list"
          >
            {(Object.keys(LIST_META) as ListType[]).map((lt) => {
              const LIcon = LIST_ICONS[lt];
              const a = LIST_ACCENTS[lt];
              const sel = targetList === lt;
              return (
                <button
                  key={lt}
                  type="button"
                  role="tab"
                  aria-selected={sel}
                  onClick={() => setTargetList(lt)}
                  className={`inline-flex flex-1 min-w-[5.5rem] items-center justify-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors border sm:min-w-0 sm:flex-initial ${
                    sel
                      ? a.tabActive
                      : "border-transparent text-gray-500 hover:text-gray-300 hover:bg-surface-800/80"
                  }`}
                >
                  <LIcon className="w-4 h-4 shrink-0 opacity-90" />
                  <span className="truncate">{LIST_META[lt].label}</span>
                </button>
              );
            })}
          </div>
          <p className="text-xs text-gray-500 mt-3 leading-relaxed">{LIST_META[targetList].description}</p>
        </div>
        <div className="p-5 space-y-3">
          <div>
            <label className="text-xs font-medium text-gray-500 block mb-1">Entity ID</label>
            <input
              placeholder="Required"
              value={form.entity_id}
              onChange={(e) => setForm({ ...form, entity_id: e.target.value })}
              className="w-full bg-surface-950 border border-surface-600 rounded-xl px-3 py-2.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-brand-500/50"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-500 block mb-1">Reason</label>
            <input
              placeholder="Optional note"
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
              className="w-full bg-surface-950 border border-surface-600 rounded-xl px-3 py-2.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-brand-500/50"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-500 block mb-1">Created by</label>
            <input
              value={form.created_by}
              onChange={(e) => setForm({ ...form, created_by: e.target.value })}
              className="w-full bg-surface-950 border border-surface-600 rounded-xl px-3 py-2.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-brand-500/50"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-500 block mb-1">Expires (optional)</label>
            <input
              type="datetime-local"
              value={form.expires_at}
              onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
              className="w-full bg-surface-950 border border-surface-600 rounded-xl px-3 py-2.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-brand-500/50"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-surface-700 bg-surface-900/80 rounded-b-2xl">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-400 hover:text-gray-200 rounded-xl transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={submitting || !form.entity_id.trim()}
            className="px-4 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:pointer-events-none text-white text-sm font-medium transition-colors"
          >
            {submitting ? "Adding…" : `Add to ${LIST_META[targetList].label}`}
          </button>
        </div>
      </div>
    </div>
  );
}
