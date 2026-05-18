import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { integrations, type KycHandoverCaseRow } from "../../api/client";
import { toUserFacingError } from "../../utils/userFacingErrors";

type Props = {
  caseId: string;
  tenantId: string;
};

export function KycHandoverPanel({ caseId, tenantId }: Props): ReactElement | null {
  const [row, setRow] = useState<KycHandoverCaseRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const board = await integrations.kycHandover({ tenant_id: tenantId, case_id: caseId });
      setRow(board.cases[0] ?? null);
      setError(null);
    } catch (e) {
      setRow(null);
      setError(toUserFacingError(e, { subject: "KYC handover", action: "load status" }));
    } finally {
      setLoading(false);
    }
  }, [caseId, tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const sendEmail = useCallback(async () => {
    setBusy(true);
    setSuccess(null);
    try {
      const res = await integrations.kycHandoverSendEmail({
        tenant_id: tenantId,
        case_id: caseId,
        analyst_note: note.trim() || undefined,
      });
      if (!res.ok || !res.handover || !res.email) {
        setError(res.error ?? "Unable to send KYC email");
        return;
      }
      setRow(res.handover);
      setSuccess(`Email sent to ${res.email.to}`);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "KYC handover", action: "send ID request email" }));
    } finally {
      setBusy(false);
    }
  }, [caseId, tenantId, note]);

  if (loading) {
    return (
      <div className="rounded-xl border border-surface-700 bg-surface-900/50 px-4 py-3 text-xs text-gray-500">
        Loading KYC handover…
      </div>
    );
  }

  if (!row || row.kyc_status !== "needs_more_id") {
    return null;
  }

  return (
    <section className="rounded-xl border border-teal-500/30 bg-teal-950/15 p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-teal-200">KYC handover</h3>
          <p className="text-xs text-gray-500 mt-1 max-w-xl">
            This case needs additional identity documents. Send an automated email to{" "}
            <span className="font-mono text-gray-400">{row.subject_email}</span> with upload instructions.
          </p>
        </div>
        <Link
          to="/compliance/kyc-handover"
          className="text-[10px] font-semibold text-brand-400 hover:text-brand-300 shrink-0"
        >
          Open handover board →
        </Link>
      </div>

      <ul className="text-[10px] text-gray-400 flex flex-wrap gap-2">
        {row.documents_requested.map((doc) => (
          <li key={doc} className="rounded border border-surface-600 px-2 py-0.5 font-mono uppercase">
            {doc.replace(/_/g, " ")}
          </li>
        ))}
      </ul>

      {row.handover_status === "email_sent" ? (
        <p className="text-xs text-emerald-300/90">
          Email sent {row.email_sent_at ? new Date(row.email_sent_at).toLocaleString() : ""}
          {row.email_message_id ? (
            <>
              {" "}
              · <span className="font-mono text-gray-500">{row.email_message_id}</span>
            </>
          ) : null}
        </p>
      ) : (
        <>
          <label className="text-xs text-gray-500 block">
            Optional note for the user
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder="e.g. Please provide a clear photo of your government-issued ID."
              className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-3 py-2 text-sm text-gray-100 resize-y"
            />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() => void sendEmail()}
            className="text-xs font-semibold px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white disabled:opacity-50"
          >
            {busy ? "Sending…" : "Send ID request email"}
          </button>
        </>
      )}

      {error ? <p className="text-xs text-rose-300">{error}</p> : null}
      {success ? <p className="text-xs text-emerald-300">{success}</p> : null}
    </section>
  );
}
