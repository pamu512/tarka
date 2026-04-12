import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAnalystWorkspace } from "../context/AnalystWorkspaceContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { parseCaseDetailRoute, parseCaseOpenInput } from "../utils/caseOpenQuery";
import { ModuleIcon, type ModuleId } from "./ModuleIcon";

type CommandItem = {
  id: string;
  label: string;
  hint?: string;
  module?: ModuleId;
  keywords?: string;
  run: () => void;
};

const MODULE_ROUTES: Array<{ to: string; label: string; module: ModuleId; keywords: string }> = [
  { to: "/dashboard", label: "Dashboard", module: "dashboard", keywords: "home overview" },
  { to: "/cases", label: "Cases queue", module: "cases", keywords: "list triage" },
  { to: "/disputes", label: "Disputes", module: "disputes", keywords: "chargeback" },
  { to: "/graph", label: "Graph Explorer", module: "graph", keywords: "network neo4j" },
  { to: "/investigation", label: "Investigation Copilot", module: "investigation", keywords: "chat saarthi llm" },
  { to: "/osint", label: "OSINT enrichment", module: "osint", keywords: "intel" },
  { to: "/analytics", label: "Analytics", module: "analytics", keywords: "metrics charts" },
  { to: "/rules", label: "Rules", module: "rules", keywords: "policy" },
  { to: "/entity-lists", label: "Entity lists", module: "entity-lists", keywords: "block allow" },
  { to: "/shadow", label: "Shadow mode", module: "shadow", keywords: "dry run" },
  { to: "/simulation", label: "Simulation", module: "simulation", keywords: "ab test" },
  { to: "/compliance", label: "Compliance", module: "compliance", keywords: "audit" },
  { to: "/integrations", label: "Integrations", module: "integrations", keywords: "connectors" },
  { to: "/admin", label: "Admin panel", module: "admin", keywords: "platform" },
  { to: "/notifications", label: "Notifications", module: "notifications", keywords: "alerts" },
  { to: "/settings", label: "Settings", module: "settings", keywords: "theme appearance" },
  { to: "/help", label: "Help & guide", module: "help", keywords: "docs" },
];

function normalize(s: string) {
  return s.toLowerCase().trim();
}

function matchesQuery(item: CommandItem, q: string) {
  if (!q) return true;
  const n = normalize(q);
  return (
    normalize(item.label).includes(n) ||
    (item.keywords && normalize(item.keywords).includes(n)) ||
    (item.hint && normalize(item.hint).includes(n))
  );
}

function copilotUrl(caseId: string, tenantId: string) {
  return `/investigation?case_id=${encodeURIComponent(caseId)}&tenant_id=${encodeURIComponent(tenantId)}`;
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const { openCases, pinCase } = useAnalystWorkspace();
  const { tenantId: workspaceTenantId } = useTenantEnvironment();

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setSelectedIndex(0);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        e.preventDefault();
        close();
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener("tarka-open-command-palette", onOpen);
    return () => window.removeEventListener("tarka-open-command-palette", onOpen);
  }, []);

  useEffect(() => {
    if (open) {
      const t = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(t);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query, open]);

  const routeCase = useMemo(
    () => parseCaseDetailRoute(location.pathname),
    [location.pathname],
  );
  const tenantOnCasePage = useMemo(() => {
    const sp = new URLSearchParams(location.search);
    return sp.get("tenant_id") ?? workspaceTenantId;
  }, [location.search, workspaceTenantId]);

  const items = useMemo(() => {
    const out: CommandItem[] = [];
    const q = query.trim();

    const contextual: CommandItem[] = [];
    if (routeCase) {
      contextual.push({
        id: "ctx:copilot-this-case",
        label: "Investigation Copilot (this case)",
        hint: `${routeCase.caseId.slice(0, 14)}${routeCase.caseId.length > 14 ? "…" : ""} · ${tenantOnCasePage}`,
        module: "investigation",
        keywords: "copilot chat saarthi this case current",
        run: () => {
          navigate(copilotUrl(routeCase.caseId, tenantOnCasePage));
          close();
        },
      });
    } else if (openCases[0]) {
      const t = openCases[0];
      contextual.push({
        id: "ctx:copilot-latest-tab",
        label: "Investigation Copilot (latest open case)",
        hint: `${t.title} · ${t.tenantId}`,
        module: "investigation",
        keywords: "copilot chat saarthi recent tab",
        run: () => {
          navigate(copilotUrl(t.caseId, t.tenantId));
          close();
        },
      });
    }

    for (const c of contextual) {
      if (matchesQuery(c, q)) out.push(c);
    }

    for (const m of MODULE_ROUTES) {
      const item: CommandItem = {
        id: `mod:${m.to}`,
        label: m.label,
        hint: "Module",
        module: m.module,
        keywords: m.keywords,
        run: () => {
          navigate(m.to);
          close();
        },
      };
      if (matchesQuery(item, q)) out.push(item);
    }

    for (const tab of openCases) {
      const item: CommandItem = {
        id: `case:${tab.tenantId}:${tab.caseId}`,
        label: tab.title || "Case",
        hint: `Open case · ${tab.caseId.slice(0, 10)}… · ${tab.tenantId}`,
        module: "cases",
        keywords: `${tab.caseId} ${tab.tenantId} ${tab.title}`,
        run: () => {
          navigate(
            `/cases/${encodeURIComponent(tab.caseId)}?tenant_id=${encodeURIComponent(tab.tenantId)}`,
          );
          close();
        },
      };
      if (matchesQuery(item, q)) out.push(item);
    }

    const parsed = parseCaseOpenInput(q, workspaceTenantId);
    if (parsed) {
      const alreadyOpen = openCases.some(
        (t) => t.caseId === parsed.caseId && t.tenantId === parsed.tenantId,
      );
      const showOpenRow = !alreadyOpen || q.includes("/");
      if (showOpenRow) {
        out.unshift({
          id: `open-id:${parsed.tenantId}:${parsed.caseId}`,
          label: q.includes("/") ? "Open case (tenant / id)" : "Open case by ID",
          hint: `${parsed.tenantId} · ${parsed.caseId}`,
          module: "cases",
          keywords: `${parsed.caseId} ${parsed.tenantId}`,
          run: () => {
            pinCase({
              caseId: parsed.caseId,
              tenantId: parsed.tenantId,
              title: parsed.caseId,
            });
            navigate(
              `/cases/${encodeURIComponent(parsed.caseId)}?tenant_id=${encodeURIComponent(parsed.tenantId)}`,
            );
            close();
          },
        });
      }
    }

    return out;
  }, [
    query,
    openCases,
    navigate,
    close,
    pinCase,
    workspaceTenantId,
    routeCase,
    tenantOnCasePage,
  ]);

  useEffect(() => {
    setSelectedIndex((i) => {
      if (items.length === 0) return 0;
      return Math.min(i, items.length - 1);
    });
  }, [items.length]);

  useLayoutEffect(() => {
    if (!listRef.current || items.length === 0) return;
    listRef.current
      .querySelector(`[data-cmd-index="${selectedIndex}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedIndex, items.length, open]);

  const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(items.length - 1, i + 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(0, i - 1));
      return;
    }
    if (e.key === "Enter" && items.length > 0) {
      e.preventDefault();
      items[selectedIndex]?.run();
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center pt-[12vh] px-4 bg-black/55 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-surface-600 bg-surface-900 shadow-2xl shadow-black/50 overflow-hidden animate-fade-in"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="border-b border-surface-700 px-3 py-2 flex items-center gap-2">
          <span className="text-gray-500 text-sm shrink-0" aria-hidden>
            ⌕
          </span>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Modules, case title… or tenant/case-id"
            className="flex-1 min-w-0 bg-transparent text-sm text-gray-100 placeholder:text-gray-600 focus:outline-none py-2"
            aria-label="Search commands"
            aria-controls="command-palette-listbox"
            aria-activedescendant={
              items.length > 0 ? `cmd-opt-${selectedIndex}` : undefined
            }
          />
          <kbd className="hidden sm:inline text-[10px] text-gray-600 border border-surface-600 rounded px-1.5 py-0.5 shrink-0">
            esc
          </kbd>
        </div>
        <ul
          ref={listRef}
          id="command-palette-listbox"
          className="max-h-[min(50vh,360px)] overflow-y-auto py-1"
          role="listbox"
          aria-label="Commands"
        >
          {items.length === 0 ? (
            <li className="px-4 py-8 text-center text-sm text-gray-500">No matches</li>
          ) : (
            items.map((item, idx) => {
              const active = idx === selectedIndex;
              const domId = `cmd-opt-${idx}`;
              return (
                <li key={item.id} role="presentation">
                  <button
                    id={domId}
                    data-cmd-index={idx}
                    type="button"
                    role="option"
                    aria-selected={active}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    onClick={() => item.run()}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 text-left focus:outline-none ${
                      active ? "bg-brand-600/20 text-gray-100" : "hover:bg-surface-800/90 text-gray-200"
                    }`}
                  >
                    {item.module ? (
                      <ModuleIcon
                        module={item.module}
                        className="w-4 h-4 shrink-0 text-gray-500"
                        aria-hidden
                      />
                    ) : (
                      <span className="w-4 h-4 shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="text-sm truncate">{item.label}</div>
                      {item.hint ? (
                        <div className="text-xs text-gray-500 truncate">{item.hint}</div>
                      ) : null}
                    </div>
                  </button>
                </li>
              );
            })
          )}
        </ul>
        <div className="border-t border-surface-800 px-3 py-2 text-[11px] text-gray-600 flex flex-wrap gap-x-3 gap-y-1">
          <span>
            <kbd className="font-mono text-gray-500">↑</kbd>{" "}
            <kbd className="font-mono text-gray-500">↓</kbd> move ·{" "}
            <kbd className="font-mono text-gray-500">↵</kbd> run
          </span>
          <span>
            <kbd className="font-mono text-gray-500">⌘K</kbd> toggle
          </span>
          <span className="hidden sm:inline">Use tenant/id for cross-tenant case opens</span>
        </div>
      </div>
    </div>
  );
}

/** Toolbar / menu: open the palette without toggling closed. */
export function requestOpenCommandPalette() {
  window.dispatchEvent(new Event("tarka-open-command-palette"));
}
