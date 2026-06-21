import { useCallback, useState } from "react";
import { investigation, type InvestigationEvidenceSummaryCitation } from "../../../api/client";
import { ShadowChatSidebar } from "../ShadowChatSidebar";
import { CopilotCitationCards } from "./CopilotCitationCards";
import { useCaseWorkbench } from "../../../context/CaseWorkbenchContext";
import { toUserFacingApiError } from "../../../api/client";
import { trackPanelUsage, trackWorkbenchTask } from "../../../workbench/workbenchTelemetry";

const DEFAULT_ANALYST = "analyst-1";

/** Embedded copilot rail: Shadow sidecar + investigation citations (E02). */
export function CopilotWorkbenchRail() {
  const { caseId, tenantId, caseData, copilotRailOpen, setCopilotRailOpen, isPanelOpen } = useCaseWorkbench();
  const [citations, setCitations] = useState<InvestigationEvidenceSummaryCitation[]>([]);
  const [citationLoading, setCitationLoading] = useState(false);
  const [citationError, setCitationError] = useState<string | null>(null);
  const [lastPrompt, setLastPrompt] = useState("Summarize this case for triage.");

  const open = isPanelOpen("copilot_rail") && copilotRailOpen;

  const refreshCitations = useCallback(async () => {
    if (!caseData?.trace_id) {
      setCitationError("No trace on this case — citations require an audit trace.");
      setCitations([]);
      return;
    }
    setCitationLoading(true);
    setCitationError(null);
    try {
      const res = await investigation.evidenceSummary({
        tenant_id: tenantId,
        analyst_id: DEFAULT_ANALYST,
        case_id: caseId,
        trace_id: caseData.trace_id,
        reply: lastPrompt,
        claims: [{ text: lastPrompt, source: "unknown" }],
      });
      setCitations(res.citations ?? []);
      trackWorkbenchTask("copilot_citations_refresh", { caseId, tenantId });
    } catch (e) {
      setCitations([]);
      setCitationError(toUserFacingApiError(e, { subject: "Copilot citations", action: "load evidence summary" }));
    } finally {
      setCitationLoading(false);
    }
  }, [caseData?.trace_id, tenantId, caseId, lastPrompt]);

  if (!isPanelOpen("copilot_rail")) return null;

  return (
    <aside
      className={`shrink-0 flex flex-col border-l border-surface-700 bg-surface-950/40 transition-[width] ${
        open ? "w-full xl:w-[min(100%,22rem)]" : "w-0 overflow-hidden border-l-0"
      }`}
      aria-label="Copilot rail"
    >
      {open ? (
        <>
          <div className="shrink-0 border-b border-surface-700 px-3 py-2 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-gray-300">Copilot rail</span>
            <button
              type="button"
              onClick={() => {
                setCopilotRailOpen(false);
                trackPanelUsage("copilot_rail", false, { caseId, tenantId });
              }}
              className="text-[11px] text-gray-500 hover:text-gray-300"
            >
              Collapse
            </button>
          </div>
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            <ShadowChatSidebar
              caseId={caseId}
              tenantId={tenantId}
              caseTitle={caseData?.title ?? undefined}
              open
              onOpenChange={(v) => {
                if (!v) setCopilotRailOpen(false);
              }}
              embedded
            />
            <div className="shrink-0 border-t border-surface-700">
              <div className="flex items-center justify-between gap-2 px-3 py-2">
                <span className="text-[10px] uppercase tracking-wide text-gray-500">Citation cards</span>
                <button
                  type="button"
                  disabled={citationLoading}
                  onClick={() => void refreshCitations()}
                  className="text-[10px] text-brand-400 hover:text-brand-300 disabled:opacity-45"
                >
                  {citationLoading ? "Loading…" : "Refresh"}
                </button>
              </div>
              <label className="sr-only" htmlFor="copilot-citation-prompt">
                Citation prompt
              </label>
              <input
                id="copilot-citation-prompt"
                value={lastPrompt}
                onChange={(e) => setLastPrompt(e.target.value)}
                className="mx-3 mb-2 w-[calc(100%-1.5rem)] bg-surface-900 border border-surface-700 text-gray-400 text-[11px] rounded px-2 py-1"
              />
              <CopilotCitationCards citations={citations} loading={citationLoading} error={citationError} />
            </div>
          </div>
        </>
      ) : null}
    </aside>
  );
}
