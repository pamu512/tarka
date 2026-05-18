import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  integrations,
  type KycHandoverCaseRow,
  type KycHandoverBoardResponse,
} from "../api/client";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { toUserFacingError } from "../utils/userFacingErrors";

function handoverTone(status: string): string {
  if (status === "pending") return "border-amber-500/40 text-amber-200 bg-amber-950/20";
  if (status === "email_sent") return "border-emerald-500/40 text-emerald-200 bg-emerald-950/20";
  return "border-surface-600 text-gray-400";
}

export default function KycHandover(): ReactElement {
  const { tenantId } = useTenantEnvironment();
  const [data, setData] = useState<KycHandoverBoardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyCaseId, setBusyCaseId] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  useRegisterPageMeta({ title: "KYC handover", subtitle: "Additional ID requests" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrations.kycHandover({ tenant_id: tenantId });
      setData(res);
      setError(null);
    } catch (e) {
      setData(null);
      setError(toUserFacingError(e, { subject: "KYC handover", action: "load board" }));
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const sendForCase = useCallback(
    async (caseId: string) => {
      setBusyCaseId(caseId);
      try {
        const res = await integrations.kycHandoverSendEmail({
          tenant_id: tenantId,
          case_id: caseId,
          analyst_note: notes[caseId]?.trim() || undefined,
        });
        if (!res.ok || !res.handover) {
          setError(res.error ?? "Send failed");
          return;
        }
        setData((prev) =>
          prev
            ? {
                ...prev,
                cases: prev.cases.map((c) => (c.case_id === caseId ? res.handover! : c)),
                summary: {
                  ...prev.summary,
                  pending_email_count: Math.max(0, prev.summary.pending_email_count - 1),
                  email_sent_count: prev.summary.email_sent_count + 1,
                },
              }
            : prev,
        );
        setError(null);
      } catch (e) {
        setError(toUserFacingError(e, { subject: "KYC handover", action: "send email" }));
      } finally {
        setBusyCaseId(null);
      }
    },
    [tenantId, notes],
  );

  const needsIdCases = (data?.cases ?? []).filter((c) => c.kyc_status === "needs_more_id");

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <PageTitle module="compliance">KYC handover</PageTitle>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
            When a case needs more identity proof, trigger an <strong className="text-gray-300">automated email</strong>{" "}
            to the subject with the document checklist and secure upload instructions.
          </p>
          <p className="text-[11px] text-gray-600 mt-2 font-mono">
            GET /api/ingress/v1/compliance/kyc-handover · POST …/send-id-email
          </p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => void load()}
          className="text-xs font-semibold px-3 py-2 rounded-lg border border-surface-600 bg-surface-800 text-gray-200 hover:bg-surface-700 disabled:opacity-50"
        >
          Refresh
        </button>
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
          {error}
          <SupportIdHint className="mt-2" />
        </div>
      ) : null}

      {loading && !data ? (
        <p className="text-sm text-gray-500 py-16 text-center">Loading handover queue…</p>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <Stat label="Needs more ID" value={data.summary.needs_more_id_count} accent="teal" />
            <Stat label="Pending email" value={data.summary.pending_email_count} accent="amber" />
            <Stat label="Emails sent" value={data.summary.email_sent_count} />
          </div>

          <p className="text-[11px] text-gray-600">
            Template <span className="font-mono text-gray-400">{data.email_template_id}</span> · default docs:{" "}
            {data.default_documents_requested.map((d) => d.replace(/_/g, " ")).join(", ")}
          </p>

          <section className="rounded-xl border border-surface-700 overflow-hidden divide-y divide-surface-800">
            {needsIdCases.map((row) => (
              <CaseRow
                key={row.case_id}
                row={row}
                tenantId={data.tenant_id}
                note={notes[row.case_id] ?? ""}
                onNoteChange={(v) => setNotes((n) => ({ ...n, [row.case_id]: v }))}
                busy={busyCaseId === row.case_id}
                onSend={() => void sendForCase(row.case_id)}
              />
            ))}
            {needsIdCases.length === 0 ? (
              <p className="text-sm text-gray-500 py-12 text-center">No cases awaiting KYC handover.</p>
            ) : null}
          </section>
        </>
      ) : null}
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: string;
}): ReactElement {
  const tone =
    accent === "teal"
      ? "border-teal-500/35 bg-teal-950/20"
      : accent === "amber"
        ? "border-amber-500/35 bg-amber-950/20"
        : "border-surface-700 bg-surface-900/50";
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone}`}>
      <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className="text-2xl font-bold tabular-nums text-gray-100 mt-1">{value}</p>
    </div>
  );
}

function CaseRow({
  row,
  tenantId,
  note,
  onNoteChange,
  busy,
  onSend,
}: {
  row: KycHandoverCaseRow;
  tenantId: string;
  note: string;
  onNoteChange: (v: string) => void;
  busy: boolean;
  onSend: () => void;
}): ReactElement {
  return (
    <article className="px-4 py-4 hover:bg-surface-900/30 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/cases/${encodeURIComponent(row.case_id)}?tenant_id=${encodeURIComponent(tenantId)}`}
              className="font-mono text-sm text-brand-400 hover:text-brand-300"
            >
              {row.case_id}
            </Link>
            <span
              className={`text-[9px] uppercase px-1.5 py-0.5 rounded border font-semibold ${handoverTone(row.handover_status)}`}
            >
              {row.handover_status.replace(/_/g, " ")}
            </span>
            {row.priority === "high" ? (
              <span className="text-[9px] uppercase text-rose-300 font-semibold">high value</span>
            ) : null}
          </div>
          <p className="text-xs text-gray-400 mt-1">{row.case_title}</p>
          <p className="text-[10px] text-gray-600 mt-0.5">
            {row.display_name} · <span className="font-mono">{row.subject_email}</span>
          </p>
        </div>
        <p className="text-lg font-bold tabular-nums text-gray-200">${row.amount_usd.toLocaleString()}</p>
      </div>

      {row.handover_status === "email_sent" ? (
        <p className="text-xs text-emerald-300/90">
          Sent {row.email_sent_at ? new Date(row.email_sent_at).toLocaleString() : ""} · {row.email_subject}
        </p>
      ) : (
        <div className="flex flex-wrap gap-3 items-end">
          <label className="text-xs text-gray-500 flex-1 min-w-[200px]">
            Analyst note (optional)
            <input
              value={note}
              onChange={(e) => onNoteChange(e.target.value)}
              className="mt-1 w-full rounded-md border border-surface-600 bg-surface-900 px-3 py-2 text-sm text-gray-100"
              placeholder="Additional instructions for the user"
            />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={onSend}
            className="rounded-lg bg-teal-600 hover:bg-teal-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white shrink-0"
          >
            {busy ? "Sending…" : "Send ID request email"}
          </button>
        </div>
      )}
    </article>
  );
}
