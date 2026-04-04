import { useCallback, useEffect, useState } from "react";
import { disputes, type DisputeEntry, type DisputeStats } from "../api/client";
import { PageTitle } from "../components/PageTitle";

const TENANT = "demo";

const STATUS_COLORS: Record<string, string> = {
  filed: "bg-blue-600",
  investigating: "bg-yellow-600",
  evidence_submitted: "bg-purple-600",
  accepted: "bg-green-600",
  rejected: "bg-red-600",
  resolved: "bg-gray-600",
};

const OUTCOME_COLORS: Record<string, string> = {
  fraud_confirmed: "bg-red-500",
  false_positive: "bg-green-500",
  inconclusive: "bg-gray-500",
  merchant_fault: "bg-orange-500",
  customer_fault: "bg-blue-500",
};

export default function Disputes() {
  const [items, setItems] = useState<DisputeEntry[]>([]);
  const [stats, setStats] = useState<DisputeStats | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<DisputeEntry | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [listRes, statsRes] = await Promise.all([
        disputes.list(TENANT, filter ? { status: filter } : undefined),
        disputes.stats(TENANT),
      ]);
      setItems(listRes.items);
      setStats(statsRes);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <PageTitle module="disputes">Disputes & Chargebacks</PageTitle>
        <button onClick={() => setShowCreate(true)} className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-sm font-medium transition-colors">
          + File Dispute
        </button>
      </div>

      {stats && <StatsBar stats={stats} />}

      <div className="flex gap-2">
        {["", "filed", "investigating", "accepted", "rejected", "resolved"].map((s) => (
          <button key={s} onClick={() => setFilter(s)} className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${filter === s ? "bg-brand-600 text-white" : "bg-surface-800 text-gray-400 hover:bg-surface-700"}`}>
            {s || "All"}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-gray-400 text-center py-12">Loading...</div>
      ) : items.length === 0 ? (
        <div className="text-gray-500 text-center py-12">No disputes found</div>
      ) : (
        <div className="bg-surface-900 rounded-xl border border-surface-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700 text-gray-400 text-left">
                <th className="px-4 py-3 font-medium">Entity</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Amount</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Outcome</th>
                <th className="px-4 py-3 font-medium">Original Decision</th>
                <th className="px-4 py-3 font-medium">Filed</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.id} className="border-b border-surface-800 hover:bg-surface-800/50 transition-colors">
                  <td className="px-4 py-3 text-gray-200 font-mono text-xs">{d.entity_id}</td>
                  <td className="px-4 py-3 text-gray-300 capitalize">{d.dispute_type.replace("_", " ")}</td>
                  <td className="px-4 py-3 text-gray-200">{d.currency} {d.amount.toFixed(2)}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs text-white ${STATUS_COLORS[d.status] || "bg-gray-600"}`}>{d.status}</span>
                  </td>
                  <td className="px-4 py-3">
                    {d.outcome ? (
                      <span className={`px-2 py-0.5 rounded text-xs text-white ${OUTCOME_COLORS[d.outcome] || "bg-gray-600"}`}>{d.outcome.replace("_", " ")}</span>
                    ) : <span className="text-gray-500">-</span>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs ${d.original_decision === "deny" ? "bg-red-600/20 text-red-400" : d.original_decision === "review" ? "bg-yellow-600/20 text-yellow-400" : "bg-green-600/20 text-green-400"}`}>
                      {d.original_decision || "N/A"} {d.original_score != null ? `(${d.original_score.toFixed(0)})` : ""}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">{d.filed_at ? new Date(d.filed_at).toLocaleDateString() : "-"}</td>
                  <td className="px-4 py-3">
                    <button onClick={() => setSelected(d)} className="text-brand-400 hover:text-brand-300 text-xs font-medium">View</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && <CreateDisputeModal onClose={() => setShowCreate(false)} onCreated={load} />}
      {selected && <DisputeDetailModal dispute={selected} onClose={() => setSelected(null)} onUpdated={load} />}
    </div>
  );
}

function StatsBar({ stats }: { stats: DisputeStats }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-4">
        <div className="text-xs text-gray-400 mb-1">Total Disputes</div>
        <div className="text-2xl font-bold text-gray-100">{stats.total}</div>
      </div>
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-4">
        <div className="text-xs text-gray-400 mb-1">Active</div>
        <div className="text-2xl font-bold text-blue-400">{(stats.by_status.filed || 0) + (stats.by_status.investigating || 0)}</div>
      </div>
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-4">
        <div className="text-xs text-gray-400 mb-1">Win Rate</div>
        <div className="text-2xl font-bold text-green-400">{(stats.win_rate * 100).toFixed(1)}%</div>
      </div>
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-4">
        <div className="text-xs text-gray-400 mb-1">Disputed Amount</div>
        <div className="text-2xl font-bold text-yellow-400">${stats.total_amount.toLocaleString()}</div>
      </div>
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-4">
        <div className="text-xs text-gray-400 mb-1">Fraud Confirmed</div>
        <div className="text-2xl font-bold text-red-400">{stats.by_outcome.fraud_confirmed || 0}</div>
      </div>
    </div>
  );
}

function CreateDisputeModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({
    entity_id: "", trace_id: "", dispute_type: "chargeback", reason_code: "", amount: "0", currency: "USD", merchant_id: "", card_network: "",
  });
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    try {
      await disputes.create({
        tenant_id: TENANT,
        entity_id: form.entity_id,
        trace_id: form.trace_id,
        dispute_type: form.dispute_type,
        reason_code: form.reason_code,
        amount: parseFloat(form.amount) || 0,
        currency: form.currency,
        merchant_id: form.merchant_id || undefined,
        card_network: form.card_network || undefined,
      });
      onCreated();
      onClose();
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-surface-900 border border-surface-700 rounded-2xl p-6 w-full max-w-lg space-y-4">
        <h2 className="text-lg font-bold text-gray-100">File New Dispute</h2>
        <div className="grid grid-cols-2 gap-3">
          <input placeholder="Entity ID *" value={form.entity_id} onChange={(e) => setForm({ ...form, entity_id: e.target.value })} className="col-span-2 bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
          <input placeholder="Trace ID *" value={form.trace_id} onChange={(e) => setForm({ ...form, trace_id: e.target.value })} className="col-span-2 bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
          <select value={form.dispute_type} onChange={(e) => setForm({ ...form, dispute_type: e.target.value })} className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200">
            <option value="chargeback">Chargeback</option>
            <option value="dispute">Dispute</option>
            <option value="fraud_claim">Fraud Claim</option>
            <option value="unauthorized">Unauthorized</option>
            <option value="service_not_rendered">Service Not Rendered</option>
            <option value="product_not_received">Product Not Received</option>
          </select>
          <input placeholder="Reason Code" value={form.reason_code} onChange={(e) => setForm({ ...form, reason_code: e.target.value })} className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
          <input placeholder="Amount" type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
          <input placeholder="Currency" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })} className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
          <input placeholder="Merchant ID" value={form.merchant_id} onChange={(e) => setForm({ ...form, merchant_id: e.target.value })} className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
          <select value={form.card_network} onChange={(e) => setForm({ ...form, card_network: e.target.value })} className="bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200">
            <option value="">Card Network</option>
            <option value="visa">Visa</option>
            <option value="mastercard">Mastercard</option>
            <option value="amex">Amex</option>
            <option value="discover">Discover</option>
          </select>
        </div>
        <div className="flex justify-end gap-3 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200">Cancel</button>
          <button onClick={submit} disabled={submitting || !form.entity_id || !form.trace_id} className="px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium">
            {submitting ? "Filing..." : "File Dispute"}
          </button>
        </div>
      </div>
    </div>
  );
}

function DisputeDetailModal({ dispute, onClose, onUpdated }: { dispute: DisputeEntry; onClose: () => void; onUpdated: () => void }) {
  const [outcome, setOutcome] = useState(dispute.outcome || "");
  const [notes, setNotes] = useState(dispute.resolution_notes || "");
  const [saving, setSaving] = useState(false);

  const resolve = async () => {
    if (!outcome) return;
    setSaving(true);
    try {
      await disputes.update(dispute.id, { outcome, resolution_notes: notes });
      onUpdated();
      onClose();
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-surface-900 border border-surface-700 rounded-2xl p-6 w-full max-w-2xl space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-gray-100">Dispute Detail</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-lg">&times;</button>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div><span className="text-gray-400">Entity:</span> <span className="text-gray-200 font-mono">{dispute.entity_id}</span></div>
          <div><span className="text-gray-400">Type:</span> <span className="text-gray-200 capitalize">{dispute.dispute_type.replace("_", " ")}</span></div>
          <div><span className="text-gray-400">Amount:</span> <span className="text-gray-200">{dispute.currency} {dispute.amount.toFixed(2)}</span></div>
          <div><span className="text-gray-400">Status:</span> <span className={`px-2 py-0.5 rounded text-xs text-white ${STATUS_COLORS[dispute.status] || "bg-gray-600"}`}>{dispute.status}</span></div>
          <div><span className="text-gray-400">Trace ID:</span> <span className="text-gray-200 font-mono text-xs">{dispute.trace_id}</span></div>
          <div><span className="text-gray-400">Reason Code:</span> <span className="text-gray-200">{dispute.reason_code || "N/A"}</span></div>
          <div><span className="text-gray-400">Original Decision:</span> <span className="text-gray-200">{dispute.original_decision || "N/A"} ({dispute.original_score?.toFixed(0) ?? "?"})</span></div>
          <div><span className="text-gray-400">Rule Hits:</span> <span className="text-gray-200 text-xs">{dispute.original_rule_hits?.join(", ") || "None"}</span></div>
        </div>

        {dispute.status !== "resolved" && (
          <div className="border-t border-surface-700 pt-4 space-y-3">
            <h3 className="text-sm font-semibold text-gray-200">Resolve Dispute</h3>
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)} className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200">
              <option value="">Select Outcome...</option>
              <option value="fraud_confirmed">Fraud Confirmed</option>
              <option value="false_positive">False Positive</option>
              <option value="inconclusive">Inconclusive</option>
              <option value="merchant_fault">Merchant Fault</option>
              <option value="customer_fault">Customer Fault</option>
            </select>
            <textarea placeholder="Resolution notes..." value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200" />
            <button onClick={resolve} disabled={saving || !outcome} className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium">
              {saving ? "Saving..." : "Resolve"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
