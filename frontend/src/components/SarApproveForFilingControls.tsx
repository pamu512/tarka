import { useState } from "react";
import type { SarFilingIntentStatus } from "../api/client";
import { cases } from "../api/client";
import { persistSarApproverActorId, readSarApproverActorId } from "../utils/sarApproverActorId";
import { toUserFacingError } from "../utils/userFacingErrors";

type Props = {
  caseId: string;
  tenantId: string;
  intentId: string;
  status: SarFilingIntentStatus;
  onFiled: () => void | Promise<void>;
};

export function SarApproveForFilingControls({ caseId, tenantId, intentId, status, onFiled }: Props) {
  const [actorId, setActorId] = useState(() => readSarApproverActorId() ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (status !== "PENDING_REVIEW") {
    return null;
  }

  const trimmed = actorId.trim();
  const canSubmit = trimmed.length > 0 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setErr(null);
    try {
      await cases.approveSarFilingIntent(caseId, tenantId, intentId, { actor_id: trimmed });
      persistSarApproverActorId(trimmed);
      await onFiled();
    } catch (e) {
      setErr(toUserFacingError(e, { subject: "SAR filing approval", action: "approve this SAR for filing" }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 space-y-3"
      aria-labelledby="sar-approve-filing-heading"
    >
      <h2 id="sar-approve-filing-heading" className="text-sm font-semibold text-gray-200">
        Analyst approval
      </h2>
      <p className="text-xs text-gray-500">
        Approving for filing records a human attestation in the audit log and moves this intent to{" "}
        <span className="font-mono text-gray-400">FILED</span>. Your analyst identifier is sent as{" "}
        <span className="font-mono text-gray-400">actor_id</span> (stored locally in this browser for convenience).
      </p>
      <label className="block text-xs text-gray-400 space-y-1">
        <span>Analyst ID (required)</span>
        <input
          type="text"
          value={actorId}
          onChange={(e) => setActorId(e.target.value)}
          autoComplete="username"
          placeholder="e.g. analyst.jdoe"
          className="w-full max-w-md bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-gray-200 font-mono"
        />
      </label>
      {err ? <div className="text-sm text-rose-200/90">{err}</div> : null}
      <button
        type="button"
        disabled={!canSubmit}
        onClick={() => void submit()}
        className="rounded-lg border border-emerald-500/45 bg-emerald-600/20 px-4 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-600/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {busy ? "Approving…" : "Approve for filing"}
      </button>
    </section>
  );
}
