/**
 * Dispute review: side-by-side **uploaded PDF** vs **Shadow AI evidence report** (Prompt 127).
 * Route: `/disputes/:id`
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from 'react-router';
import { disputes, type DisputeEntry } from "../../api/v1/disputes";
import { PageTitle } from "../../components/PageTitle";
import { safeExternalHref } from "../../utils/externalLinks";
import { toUserFacingError } from "../../utils/userFacingErrors";

/** Public sample PDF (HTTPS) only when dispute id / same-origin evidence URL is missing. */
const DEMO_PDF_FALLBACK =
  "https://www.w3.org/WAI/WCAG21/working-examples/pdf-note/note.pdf";

function disputeEvidencePdfSrc(
  url: string | null | undefined,
  disputeId: string | undefined,
): string {
  const raw = (url || "").trim();
  // Same-origin case-api path (computed on DisputeOut) — iframe cannot use safeExternalHref (https-only).
  if (raw.startsWith("/api/cases/v1/disputes/") && raw.includes("/evidence-pdf")) {
    return raw;
  }
  const https = safeExternalHref(raw);
  if (https) return https;
  if (disputeId) return `/api/cases/v1/disputes/${disputeId}/evidence-pdf`;
  return DEMO_PDF_FALLBACK;
}

function friendlyFraudLabel(value: boolean | null | undefined): string {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "Unknown";
}

function friendlyFraudBadgeClass(value: boolean | null | undefined): string {
  if (value === true) return "text-amber-200 border-amber-500/45 bg-amber-500/10";
  if (value === false) return "text-emerald-200 border-emerald-500/45 bg-emerald-500/10";
  return "text-gray-300 border-surface-600 bg-surface-800";
}

export default function DisputeReviewByIdPage() {
  const { id } = useParams<{ id: string }>();
  const [row, setRow] = useState<DisputeEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reprocessing, setReprocessing] = useState(false);
  const [reprocessErr, setReprocessErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const d = await disputes.get(id);
      setRow(d);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Dispute", action: "load dispute detail" }));
      setRow(null);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleReprocess() {
    if (!row?.tenant_id || !id) return;
    setReprocessing(true);
    setReprocessErr(null);
    try {
      await disputes.reprocessExternal(
        id,
        { tenant_id: row.tenant_id, reason: "dispute detail manual reprocess" },
        crypto.randomUUID(),
      );
      await load();
    } catch (e) {
      setReprocessErr(
        toUserFacingError(e, { subject: "Dispute reprocess", action: "reprocess external provider" }),
      );
    } finally {
      setReprocessing(false);
    }
  }

  const pdfSrc = disputeEvidencePdfSrc(row?.evidence_pdf_url, row?.id ?? id);
  const shadowMd =
    row?.shadow_evidence_report_markdown?.trim() ||
    "*No Shadow evidence report is attached to this dispute yet.*";
  const reprocess = row?.latest_decision_reprocess;
  const ffRisk = row?.is_friendly_fraud_risk;

  return (
    <div className="p-6 space-y-4 min-h-0 flex flex-col">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <PageTitle module="disputes">Dispute review</PageTitle>
        <Link
          to="/disputes"
          className="text-sm text-brand-400 hover:text-brand-300"
        >
          ← Back to disputes
        </Link>
      </div>

      {id ? (
        <p className="text-xs text-gray-500 font-mono">
          Dispute ID: <span data-testid="dispute-review-id">{id}</span>
        </p>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="text-gray-400 py-12 text-center">Loading…</div>
      ) : !row ? (
        <div className="text-gray-500 py-12 text-center">Dispute not found.</div>
      ) : (
        <>
          <section
            className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-3"
            data-testid="dispute-reprocess-panel"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-sm font-medium text-gray-200">Reprocess signals</h2>
              <button
                type="button"
                disabled={reprocessing}
                onClick={() => void handleReprocess()}
                className="px-3 py-1.5 text-xs rounded border border-surface-600 hover:border-brand-500 text-gray-200 disabled:opacity-50"
                data-testid="dispute-reprocess-button"
              >
                {reprocessing ? "Reprocessing…" : "Reprocess evaluate"}
              </button>
            </div>

            {reprocessErr ? (
              <p className="text-xs text-red-300" data-testid="dispute-reprocess-error">
                {reprocessErr}
              </p>
            ) : null}

            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-gray-400">Friendly fraud risk:</span>
              <span
                className={`inline-block text-[11px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border ${friendlyFraudBadgeClass(ffRisk)}`}
                data-testid="dispute-friendly-fraud-badge"
              >
                {friendlyFraudLabel(ffRisk)}
              </span>
            </div>

            {reprocess ? (
              <dl className="grid gap-2 text-sm sm:grid-cols-2" data-testid="dispute-reprocess-details">
                <div>
                  <dt className="text-gray-500 text-xs">Decision</dt>
                  <dd className="font-mono text-gray-200">{reprocess.decision ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-gray-500 text-xs">Score</dt>
                  <dd className="font-mono text-gray-200">
                    {typeof reprocess.score === "number" ? reprocess.score.toFixed(1) : "—"}
                  </dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-gray-500 text-xs">Tags</dt>
                  <dd className="font-mono text-gray-200 text-xs break-all">
                    {(reprocess.tags?.length ? reprocess.tags.join(", ") : null) ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-gray-500 text-xs">Degraded</dt>
                  <dd className="font-mono text-gray-200">{reprocess.degraded ? "yes" : "no"}</dd>
                </div>
                <div>
                  <dt className="text-gray-500 text-xs">Error</dt>
                  <dd className="font-mono text-gray-200 text-xs break-all">{reprocess.error ?? "—"}</dd>
                </div>
              </dl>
            ) : (
              <p className="text-sm text-gray-500" data-testid="dispute-reprocess-empty">
                No reprocess evaluate result yet.
              </p>
            )}
          </section>

          <div
            className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-[70vh]"
            data-testid="dispute-review-split"
          >
            <section
              className="flex flex-col min-h-0 rounded-xl border border-surface-700 bg-surface-900 overflow-hidden"
              data-testid="dispute-review-pdf-panel"
            >
              <header className="px-4 py-2 border-b border-surface-700 text-sm font-medium text-gray-200 shrink-0">
                Uploaded evidence (PDF)
              </header>
              <div className="flex-1 min-h-[320px] bg-surface-950">
                <iframe
                  title="Dispute evidence PDF"
                  src={pdfSrc}
                  className="w-full h-full min-h-[320px] border-0"
                  data-testid="dispute-review-pdf-iframe"
                />
              </div>
            </section>

            <section
              className="flex flex-col min-h-0 rounded-xl border border-surface-700 bg-surface-900 overflow-hidden"
              data-testid="dispute-review-shadow-panel"
            >
              <header className="px-4 py-2 border-b border-surface-700 text-sm font-medium text-gray-200 shrink-0">
                Shadow AI evidence report
              </header>
              <div className="flex-1 overflow-auto p-4 text-sm text-gray-200">
                <pre
                  className="whitespace-pre-wrap font-sans text-gray-200 leading-relaxed"
                  data-testid="dispute-review-shadow-report"
                >
                  {shadowMd}
                </pre>
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
