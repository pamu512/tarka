import { useMemo } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAnalystWorkspace } from "../context/AnalystWorkspaceContext";
import { ModuleIcon } from "./ModuleIcon";

function tabKey(caseId: string, tenantId: string) {
  return `${tenantId}:${caseId}`;
}

function shortTitle(title: string, max = 28) {
  const t = title.trim() || "Untitled case";
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

export function AnalystCaseTabBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { openCases, removeCase, clearOpenCases } = useAnalystWorkspace();

  const { activeCaseId, activeTenantId } = useMemo(() => {
    const path = location.pathname;
    if (!path.startsWith("/cases/") || path === "/cases") {
      return { activeCaseId: null as string | null, activeTenantId: null as string | null };
    }
    const rest = decodeURIComponent(path.slice("/cases/".length));
    if (rest === "bulk-triage" || rest === "compare") {
      return { activeCaseId: null as string | null, activeTenantId: null as string | null };
    }
    const id = rest;
    const tenant = searchParams.get("tenant_id") ?? "demo";
    return { activeCaseId: id || null, activeTenantId: tenant };
  }, [location.pathname, searchParams]);

  const onClose = (e: React.MouseEvent, caseId: string, tenantId: string) => {
    e.preventDefault();
    e.stopPropagation();
    const isClosingActive =
      activeCaseId === caseId && activeTenantId === tenantId;
    const idx = openCases.findIndex((t) => t.caseId === caseId && t.tenantId === tenantId);
    const without = openCases.filter((t) => !(t.caseId === caseId && t.tenantId === tenantId));
    removeCase(caseId, tenantId);
    if (!isClosingActive) return;
    const fallback = without[idx] ?? without[idx - 1] ?? without[0];
    if (fallback) {
      navigate(
        `/cases/${encodeURIComponent(fallback.caseId)}?tenant_id=${encodeURIComponent(fallback.tenantId)}`,
      );
    } else {
      navigate("/cases");
    }
  };

  if (openCases.length === 0) return null;

  return (
    <div
      className="shrink-0 border-b border-surface-700 bg-surface-900/90 backdrop-blur-sm z-20"
      role="region"
      aria-label="Open cases"
    >
      <div className="flex items-stretch min-h-10 max-h-10 gap-0.5 px-2 py-1 overflow-x-auto scrollbar-thin">
        <Link
          to="/cases"
          className={`shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
            location.pathname === "/cases"
              ? "bg-brand-600/25 text-brand-300"
              : "text-gray-500 hover:text-gray-300 hover:bg-surface-800"
          }`}
          title="All cases"
        >
          <ModuleIcon module="cases" className="w-3.5 h-3.5 opacity-90" aria-hidden />
          Queue
        </Link>
        <div className="w-px bg-surface-700 shrink-0 my-1" aria-hidden />
        {openCases.map((tab) => {
          const active =
            activeCaseId === tab.caseId && activeTenantId === tab.tenantId;
          const href = `/cases/${encodeURIComponent(tab.caseId)}?tenant_id=${encodeURIComponent(tab.tenantId)}`;
          return (
            <div
              key={tabKey(tab.caseId, tab.tenantId)}
              className={`group flex items-stretch shrink-0 max-w-[200px] rounded-lg border transition-colors ${
                active
                  ? "border-brand-500/40 bg-brand-600/15"
                  : "border-transparent bg-surface-800/60 hover:bg-surface-800"
              }`}
            >
              <Link
                to={href}
                className="flex items-center min-w-0 pl-2.5 pr-1 py-1 text-xs font-medium text-gray-200"
                title={`${tab.title} (${tab.caseId})`}
              >
                <span className="truncate">{shortTitle(tab.title)}</span>
              </Link>
              <button
                type="button"
                onClick={(e) => onClose(e, tab.caseId, tab.tenantId)}
                className="shrink-0 px-1.5 rounded-r-lg text-gray-500 hover:text-gray-200 hover:bg-surface-700/80 focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-500"
                aria-label={`Close tab ${tab.title}`}
              >
                ×
              </button>
            </div>
          );
        })}
        <div className="w-px bg-surface-700 shrink-0 my-1" aria-hidden />
        <button
          type="button"
          onClick={() => {
            if (
              !window.confirm(
                "Close all open case tabs? Your session workspace will be cleared (this tab only).",
              )
            ) {
              return;
            }
            clearOpenCases();
            if (activeCaseId) navigate("/cases");
          }}
          className="shrink-0 px-2 py-1 rounded-lg text-[11px] font-medium text-gray-500 hover:text-amber-400/90 hover:bg-surface-800 transition-colors"
          title="Close every open case tab"
        >
          Clear all
        </button>
      </div>
    </div>
  );
}
