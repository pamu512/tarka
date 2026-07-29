import { Link } from 'react-router';
import { useAnalystWorkspace } from "../../../context/AnalystWorkspaceContext";
import { useCaseWorkbench } from "../../../context/CaseWorkbenchContext";
import { buildCaseComparisonHref } from "../../../utils/caseComparisonUrl";

/** Pinned cases + quick navigation (workbench pins panel). */
export function WorkbenchPinsRail() {
  const { openCases } = useAnalystWorkspace();
  const { caseId, tenantId, caseData, isPanelOpen } = useCaseWorkbench();

  if (!isPanelOpen("pins") || openCases.length <= 1) return null;

  return (
    <nav
      aria-label="Pinned cases"
      className="flex flex-wrap gap-2 rounded-lg border border-surface-700/60 bg-surface-950/30 px-3 py-2"
    >
      <span className="text-[10px] uppercase tracking-wide text-gray-500 self-center">Pins</span>
      {openCases.slice(0, 8).map((tab) => {
        const active = tab.caseId === caseId && tab.tenantId === tenantId;
        return (
          <Link
            key={`${tab.tenantId}:${tab.caseId}`}
            to={`/cases/${encodeURIComponent(tab.caseId)}?tenant_id=${encodeURIComponent(tab.tenantId)}`}
            className={`text-[11px] px-2 py-0.5 rounded-full border truncate max-w-[10rem] ${
              active
                ? "border-brand-500/40 bg-brand-600/15 text-brand-200"
                : "border-surface-600 text-gray-400 hover:text-gray-200"
            }`}
            title={tab.title}
          >
            {tab.title || tab.caseId.slice(0, 8)}
          </Link>
        );
      })}
      {caseData ? (
        <Link
          to={buildCaseComparisonHref({ tenantId, caseA: caseId })}
          className="text-[11px] text-brand-400 hover:text-brand-300 self-center ml-auto"
        >
          Compare
        </Link>
      ) : null}
    </nav>
  );
}
