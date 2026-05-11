/**
 * Dispute review: side-by-side **uploaded PDF** vs **Shadow AI evidence report** (Prompt 127).
 * Route: `/disputes/:id`
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { disputes, type DisputeEntry } from "../../api/client";
import { PageTitle } from "../../components/PageTitle";
import { toUserFacingError } from "../../utils/userFacingErrors";

/** Public sample PDF (HTTPS) for demo iframe when no tenant upload URL is present. */
const DEMO_PDF_FALLBACK =
  "https://www.w3.org/WAI/WCAG21/working-examples/pdf-note/note.pdf";

export default function DisputeReviewByIdPage() {
  const { id } = useParams<{ id: string }>();
  const [row, setRow] = useState<DisputeEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  const pdfSrc = row?.evidence_pdf_url?.trim() || DEMO_PDF_FALLBACK;
  const shadowMd =
    row?.shadow_evidence_report_markdown?.trim() ||
    "*No Shadow evidence report is attached to this dispute yet.*";

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
      )}
    </div>
  );
}
