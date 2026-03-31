import { useCallback, useEffect, useState } from "react";
import { entityLists, type ListEntryData } from "../api/client";

const TENANT = "demo";
type ListType = "whitelist" | "blacklist" | "test_bypass";

const LIST_META: Record<ListType, { label: string; color: string; icon: string; description: string }> = {
  whitelist: { label: "Whitelist", color: "bg-green-600", icon: "\u2713", description: "Entities that always receive ALLOW decisions" },
  blacklist: { label: "Blacklist", color: "bg-red-600", icon: "\u2717", description: "Entities that always receive DENY decisions" },
  test_bypass: { label: "Test Bypass", color: "bg-purple-600", icon: "\u26A0", description: "Entities evaluated fully but decision overridden to ALLOW" },
};

export default function EntityLists() {
  const [activeTab, setActiveTab] = useState<ListType>("whitelist");
  const [entries, setEntries] = useState<ListEntryData[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [checkEntity, setCheckEntity] = useState("");
  const [checkResult, setCheckResult] = useState<{ found: boolean; list_type: string | null; action: string; reason: string } | null>(null);

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

  useEffect(() => { load(); }, [load]);

  const handleRemove = async (entityId: string) => {
    if (!confirm(`Remove ${entityId} from ${activeTab}?`)) return;
    try {
      await entityLists.remove(activeTab, TENANT, entityId);
      load();
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
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Entity Lists</h1>
        <button onClick={() => setShowAdd(true)} className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-sm font-medium transition-colors">
          + Add Entry
        </button>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-3 gap-4">
        {(Object.keys(LIST_META) as ListType[]).map((lt) => (
          <div key={lt} className="bg-surface-900 border border-surface-700 rounded-xl p-4 flex items-center gap-4">
            <div className={`w-10 h-10 rounded-lg ${LIST_META[lt].color} flex items-center justify-center text-white text-lg`}>
              {LIST_META[lt].icon}
            </div>
            <div>
              <div className="text-xs text-gray-400">{LIST_META[lt].label}</div>
              <div className="text-xl font-bold text-gray-100">{stats[lt] ?? 0}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Entity check */}
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-4">
        <div className="text-sm font-medium text-gray-300 mb-2">Quick Check Entity</div>
        <div className="flex gap-2">
          <input value={checkEntity} onChange={(e) => setCheckEntity(e.target.value)} placeholder="Enter entity ID..." className="flex-1 bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" onKeyDown={(e) => e.key === "Enter" && handleCheck()} />
          <button onClick={handleCheck} className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-sm font-medium">Check</button>
        </div>
        {checkResult && (
          <div className={`mt-3 p-3 rounded-lg text-sm ${checkResult.found ? (checkResult.action === "deny" ? "bg-red-900/30 text-red-300" : "bg-green-900/30 text-green-300") : "bg-surface-800 text-gray-400"}`}>
            {checkResult.found ? (
              <>Found on <strong>{checkResult.list_type}</strong> &mdash; Action: <strong>{checkResult.action}</strong> &mdash; {checkResult.reason}</>
            ) : "Not found on any list"}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-surface-700 pb-0">
        {(Object.keys(LIST_META) as ListType[]).map((lt) => (
          <button key={lt} onClick={() => setActiveTab(lt)} className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 ${activeTab === lt ? `border-brand-400 text-brand-400` : "border-transparent text-gray-400 hover:text-gray-200"}`}>
            {LIST_META[lt].label} ({stats[lt] ?? 0})
          </button>
        ))}
      </div>

      <p className="text-xs text-gray-500">{LIST_META[activeTab].description}</p>

      {/* Entries table */}
      {loading ? (
        <div className="text-gray-400 text-center py-12">Loading...</div>
      ) : entries.length === 0 ? (
        <div className="text-gray-500 text-center py-12">No entries in {LIST_META[activeTab].label}</div>
      ) : (
        <div className="bg-surface-900 rounded-xl border border-surface-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700 text-gray-400 text-left">
                <th className="px-4 py-3 font-medium">Entity ID</th>
                <th className="px-4 py-3 font-medium">Reason</th>
                <th className="px-4 py-3 font-medium">Created By</th>
                <th className="px-4 py-3 font-medium">Expires</th>
                <th className="px-4 py-3 font-medium">Created</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.entity_id} className="border-b border-surface-800 hover:bg-surface-800/50 transition-colors">
                  <td className="px-4 py-3 text-gray-200 font-mono text-xs">{e.entity_id}</td>
                  <td className="px-4 py-3 text-gray-300">{e.reason || "-"}</td>
                  <td className="px-4 py-3 text-gray-400">{e.created_by}</td>
                  <td className="px-4 py-3 text-gray-400 text-xs">{e.expires_at ? new Date(e.expires_at).toLocaleDateString() : "Never"}</td>
                  <td className="px-4 py-3 text-gray-400 text-xs">{new Date(e.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3">
                    <button onClick={() => handleRemove(e.entity_id)} className="text-red-400 hover:text-red-300 text-xs font-medium">Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAdd && <AddEntryModal listType={activeTab} onClose={() => setShowAdd(false)} onAdded={load} />}
    </div>
  );
}

function AddEntryModal({ listType, onClose, onAdded }: { listType: ListType; onClose: () => void; onAdded: () => void }) {
  const [form, setForm] = useState({ entity_id: "", reason: "", created_by: "admin", expires_at: "" });
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (!form.entity_id.trim()) return;
    setSubmitting(true);
    try {
      await entityLists.add(listType, {
        tenant_id: TENANT,
        entity_id: form.entity_id.trim(),
        reason: form.reason,
        created_by: form.created_by,
        expires_at: form.expires_at || null,
      });
      onAdded();
      onClose();
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-surface-900 border border-surface-700 rounded-2xl p-6 w-full max-w-md space-y-4">
        <h2 className="text-lg font-bold text-gray-100">Add to {LIST_META[listType].label}</h2>
        <input placeholder="Entity ID *" value={form.entity_id} onChange={(e) => setForm({ ...form, entity_id: e.target.value })} className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
        <input placeholder="Reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
        <input placeholder="Created By" value={form.created_by} onChange={(e) => setForm({ ...form, created_by: e.target.value })} className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
        <div>
          <label className="text-xs text-gray-400 block mb-1">Expiry (optional)</label>
          <input type="datetime-local" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
        </div>
        <div className="flex justify-end gap-3 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200">Cancel</button>
          <button onClick={submit} disabled={submitting || !form.entity_id.trim()} className="px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium">
            {submitting ? "Adding..." : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}
