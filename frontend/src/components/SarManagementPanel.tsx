import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { SarFilingIntentDetail } from "../api/client";
import {
  SAR_PIPELINE_STEP_LABELS,
  extractSarFailureMessage,
  sarStatusStepIndex,
  sarTransport,
} from "../api/cases";
import { SarApproveForFilingControls } from "./SarApproveForFilingControls";
import { SarRegulatoryProgressBar } from "./SarRegulatoryProgressBar";
import { toUserFacingError } from "../utils/userFacingErrors";

type Props = {
  caseId: string;
  tenantId: string;
};

function indexOfPipelineStep(s: string): number {
  const norm = s === "APPROVED" ? "FILED" : s;
  return SAR_PIPELINE_STEP_LABELS.findIndex((x) => x.status === norm);
}

function formatDetailPreview(detail: Record<string, unknown>): string {
  try {
    const s = JSON.stringify(detail);
    return s.length > 160 ? `${s.slice(0, 157)}…` : s;
  } catch {
    return "—";
  }
}

export function SarManagementPanel({ caseId, tenantId }: Props) {
  const [intents, setIntents] = useState<SarFilingIntentDetail[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await sarTransport.listIntents(caseId, tenantId);
      setIntents(res.intents);
      setSelectedId((prev) => {
        if (prev && res.intents.some((i) => i.id === prev)) return prev;
        return res.intents[0]?.id ?? null;
      });
    } catch (e) {
      setError(toUserFacingError(e, { subject: "SAR management", action: "load SAR filing intents" }));
      setIntents([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }, [caseId, tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  const intent = useMemo(
    () => intents.find((i) => i.id === selectedId) ?? intents[0] ?? null,
    [intents, selectedId],
  );

  const status = intent?.status;
  const auditLog = intent?.audit_log ?? [];
  const failed = status === "FAILED";
  const failureMessage = failed ? extractSarFailureMessage(auditLog) : "";

  const stepDoneIndex = intent ? sarStatusStepIndex(intent.status, auditLog) : -1;

  const failEntry = failed ? [...auditLog].reverse().find((r) => r.to_status === "FAILED") : undefined;
  const failFrom = failEntry?.from_status ?? null;
  const failAtPipelineIndex = failed
    ? (() => {
        if (failFrom == null) return 0;
        const i = indexOfPipelineStep(failFrom);
        return i >= 0 ? i : 0;
      })()
    : -1;

  const canQueueTransmit = status === "FILED" || status === "APPROVED";

  const handleQueueTransmit = async () => {
    if (!intent || !canQueueTransmit || actionBusy) return;
    setActionBusy(true);
    setError(null);
    try {
      await sarTransport.queueTransmit(caseId, tenantId, intent.id);
      await load();
    } catch (e) {
      setError(toUserFacingError(e, { subject: "SAR transmit queue", action: "queue this SAR for SFTP transmit" }));
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <section
      className="rounded-xl border border-surface-700 bg-surface-900/80 p-4 space-y-4"
      aria-labelledby="sar-management-heading"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="sar-management-heading" className="text-sm font-semibold text-gray-200">
            SAR management
          </h2>
          <p className="text-xs text-gray-500 mt-0.5 max-w-prose">
            Regulatory filing state, compliance approval, and immutable audit history (Postgres-backed).
          </p>
        </div>
        {intents.length > 1 ? (
          <label className="text-xs text-gray-400 flex flex-col gap-1">
            <span>Filing intent</span>
            <select
              value={selectedId ?? ""}
              onChange={(e) => setSelectedId(e.target.value || null)}
              className="bg-surface-800 border border-surface-600 rounded-lg px-2 py-1.5 text-gray-200 text-xs font-mono min-w-[12rem]"
            >
              {intents.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.id.slice(0, 8)}… · {i.status}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <span className="inline-block w-4 h-4 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          Loading SAR intents…
        </div>
      ) : !intent ? (
        <p className="text-sm text-gray-500">
          No SAR filing intents for this case yet. Generate a SAR from your case workflow or API; intents will appear
          here with full audit history.
        </p>
      ) : (
        <>
          {failed ? (
            <div
              role="alert"
              className="rounded-lg border border-rose-500/50 bg-rose-950/40 px-4 py-3 space-y-2"
            >
              <div className="text-xs font-semibold uppercase tracking-wide text-rose-200/90">Transmit / filing failed</div>
              <p className="text-sm text-rose-50 leading-relaxed">{failureMessage}</p>
              <p className="text-xs text-rose-200/80">
                Correct the underlying issue (configuration, validation, or FinCEN connectivity), then create a new SAR
                filing intent if your policy allows re-filing.
              </p>
            </div>
          ) : null}

          <SarRegulatoryProgressBar
            variant="case_summary"
            intent={intent}
            workspaceHref={`/cases/${encodeURIComponent(caseId)}/sar-intent/${encodeURIComponent(intent.id)}?tenant_id=${encodeURIComponent(tenantId)}`}
          />

          <div className="space-y-2">
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">Pipeline status</div>
            <div className="text-sm text-gray-200">
              Current state:{" "}
              <span className="font-mono font-semibold text-brand-200">{intent.status}</span>
            </div>
            <p className="text-xs">
              <Link
                className="text-sky-400/90 hover:underline"
                to={`/cases/${encodeURIComponent(caseId)}/sar-intent/${encodeURIComponent(intent.id)}?tenant_id=${encodeURIComponent(tenantId)}`}
              >
                SAR intent detail — investigative notes &amp; FinCEN digest
              </Link>
            </p>
            <ol className="flex flex-wrap items-center gap-0 list-none p-0 m-0" aria-label="SAR filing progress">
              {SAR_PIPELINE_STEP_LABELS.map((step, idx) => {
                const isLast = idx === SAR_PIPELINE_STEP_LABELS.length - 1;
                const failedHere = failed && failAtPipelineIndex === idx;
                const done = failed ? idx < failAtPipelineIndex : stepDoneIndex >= idx;
                const current =
                  !failed &&
                  (status === step.status || (step.status === "FILED" && status === "APPROVED"));
                let circleClass =
                  "border-surface-600 bg-surface-800 text-gray-500";
                if (failedHere) {
                  circleClass = "border-rose-500 bg-rose-950/60 text-rose-200";
                } else if (done) {
                  circleClass = "border-emerald-500/70 bg-emerald-950/40 text-emerald-200";
                } else if (current) {
                  circleClass = "border-brand-400 bg-brand-950/40 text-brand-100";
                }
                const connectorDone = failed ? idx < failAtPipelineIndex : !failed && stepDoneIndex > idx;
                return (
                  <li key={step.status} className="flex items-center min-w-0">
                    <div className="flex flex-col items-center min-w-[5.5rem] max-w-[7rem]">
                      <div
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold ${circleClass}`}
                        aria-current={current ? "step" : undefined}
                      >
                        {failedHere ? "!" : done ? "✓" : idx + 1}
                      </div>
                      <span className="mt-1.5 text-[10px] leading-tight text-center text-gray-400 px-0.5">
                        {step.label}
                      </span>
                    </div>
                    {!isLast ? (
                      <div
                        className={`h-0.5 w-4 sm:w-6 shrink-0 -mt-5 ${connectorDone ? "bg-emerald-600/50" : "bg-surface-700"}`}
                        aria-hidden
                      />
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </div>

          {intent ? (
            <SarApproveForFilingControls
              caseId={caseId}
              tenantId={tenantId}
              intentId={intent.id}
              status={intent.status}
              onFiled={load}
            />
          ) : null}

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              onClick={() => void handleQueueTransmit()}
              disabled={!canQueueTransmit || actionBusy}
              title={
                !canQueueTransmit
                  ? "Queue for transmit is only available after the intent is filed (FILED) or legacy APPROVED."
                  : undefined
              }
              className="text-xs font-medium px-3 py-2 rounded-lg bg-surface-700 text-gray-200 border border-surface-600 hover:bg-surface-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {actionBusy && canQueueTransmit ? "Queuing…" : "Queue for transmit"}
            </button>
            <button
              type="button"
              onClick={() => void load()}
              disabled={actionBusy}
              className="text-xs font-medium px-3 py-2 rounded-lg text-gray-400 hover:text-gray-200 border border-transparent hover:border-surface-600 transition-colors"
            >
              Refresh
            </button>
          </div>

          <div className="space-y-2">
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">Audit trail</div>
            <div className="overflow-x-auto rounded-lg border border-surface-700">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-surface-950/80 text-gray-500 uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-2 font-medium">Timestamp (UTC)</th>
                    <th className="px-3 py-2 font-medium">From</th>
                    <th className="px-3 py-2 font-medium">To</th>
                    <th className="px-3 py-2 font-medium">User</th>
                    <th className="px-3 py-2 font-medium">Detail</th>
                    <th className="px-3 py-2 font-medium">Stack / error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-800 text-gray-300">
                  {auditLog.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-3 py-4 text-gray-500 text-center">
                        No audit rows yet.
                      </td>
                    </tr>
                  ) : (
                    auditLog.map((row) => (
                      <tr key={row.id} className="hover:bg-surface-800/40">
                        <td className="px-3 py-2 font-mono whitespace-nowrap text-gray-400">
                          {row.created_at ?? "—"}
                        </td>
                        <td className="px-3 py-2 font-mono text-gray-500">{row.from_status ?? "—"}</td>
                        <td className="px-3 py-2 font-mono">
                          <span className={row.to_status === "FAILED" ? "text-rose-300 font-semibold" : "text-gray-200"}>
                            {row.to_status}
                          </span>
                        </td>
                        <td className="px-3 py-2 font-mono text-gray-400">{row.actor ?? "—"}</td>
                        <td className="px-3 py-2 max-w-[14rem] sm:max-w-xs truncate" title={formatDetailPreview(row.detail)}>
                          {formatDetailPreview(row.detail)}
                        </td>
                        <td className="px-3 py-2 max-w-[12rem] truncate font-mono text-rose-200/90" title={row.stack_trace ?? ""}>
                          {row.stack_trace ? row.stack_trace.split("\n")[0] : "—"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
