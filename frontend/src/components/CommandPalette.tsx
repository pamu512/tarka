import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { omniSearch, type OmniSearchResponse } from "../api/client";
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

type PaletteSection = { title: string; items: CommandItem[] };

const MODULE_ROUTES: Array<{ to: string; label: string; module: ModuleId; keywords: string }> = [
  { to: "/dashboard", label: "Dashboard", module: "dashboard", keywords: "home overview" },
  { to: "/cases", label: "Cases queue", module: "cases", keywords: "list triage" },
  { to: "/disputes", label: "Disputes", module: "disputes", keywords: "chargeback" },
  { to: "/graph", label: "Graph Explorer", module: "graph", keywords: "network neo4j" },
  { to: "/investigation", label: "Investigation Copilot", module: "investigation", keywords: "chat saarthi llm" },
  {
    to: "/investigation/shadow-llm",
    label: "Shadow LLM forensics",
    module: "investigation",
    keywords: "sidecar sse stream ollama shadow copilot",
  },
  { to: "/osint", label: "OSINT enrichment", module: "osint", keywords: "intel" },
  { to: "/analytics", label: "Analytics", module: "analytics", keywords: "metrics charts" },
  { to: "/rules", label: "Rules", module: "rules", keywords: "policy" },
  { to: "/entity-lists", label: "Entity lists", module: "entity-lists", keywords: "block allow" },
  { to: "/shadow", label: "Shadow mode", module: "shadow", keywords: "dry run" },
  { to: "/simulation", label: "Simulation", module: "simulation", keywords: "ab test" },
  { to: "/ops/backtest", label: "Backtest jobs", module: "rules", keywords: "warehouse olap streaming" },
  { to: "/ops/infra", label: "Infra & health", module: "compliance", keywords: "prometheus metrics monitoring signal" },
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

const EMPTY_OMNI: OmniSearchResponse = { entities: [], cases: [], rules: [] };

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [omni, setOmni] = useState<OmniSearchResponse | null>(null);
  const [omniLoading, setOmniLoading] = useState(false);
  const [omniError, setOmniError] = useState<string | null>(null);
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
    setDebouncedQuery("");
    setOmni(null);
    setOmniLoading(false);
    setOmniError(null);
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
    if (!open) return;
    const t = window.setTimeout(() => setDebouncedQuery(query), 300);
    return () => window.clearTimeout(t);
  }, [query, open]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) return;
    const q = debouncedQuery.trim();
    if (!q) {
      setOmni(null);
      setOmniError(null);
      setOmniLoading(false);
      return;
    }
    const ac = new AbortController();
    setOmniLoading(true);
    setOmniError(null);
    (async () => {
      try {
        const data = await omniSearch({ q, tenant_id: workspaceTenantId }, ac.signal);
        setOmni(data);
      } catch (e: unknown) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (e instanceof Error && e.name === "AbortError") return;
        setOmni(null);
        setOmniError(e instanceof Error ? e.message : "Search failed");
      } finally {
        if (!ac.signal.aborted) setOmniLoading(false);
      }
    })();
    return () => ac.abort();
  }, [debouncedQuery, open, workspaceTenantId]);

  const routeCase = useMemo(
    () => parseCaseDetailRoute(location.pathname),
    [location.pathname],
  );
  const tenantOnCasePage = useMemo(() => {
    const sp = new URLSearchParams(location.search);
    return sp.get("tenant_id") ?? workspaceTenantId;
  }, [location.search, workspaceTenantId]);

  const paletteSections = useMemo((): PaletteSection[] => {
    const q = query.trim();
    const sections: PaletteSection[] = [];
    const remoteQ = debouncedQuery.trim();
    const data = omni ?? EMPTY_OMNI;

    if (remoteQ) {
      if (data.entities.length > 0) {
        sections.push({
          title: "Entities",
          items: data.entities.map((e) => ({
            id: `omni:entity:${e.tenant_id}:${e.entity_id}`,
            label: e.label,
            hint: e.subtitle ?? undefined,
            module: "graph" as ModuleId,
            keywords: `${e.entity_id} ${e.tenant_id}`,
            run: () => {
              navigate(
                `/graph?entity_id=${encodeURIComponent(e.entity_id)}&tenant_id=${encodeURIComponent(e.tenant_id)}`,
              );
              close();
            },
          })),
        });
      }
      if (data.cases.length > 0) {
        sections.push({
          title: "Cases",
          items: data.cases.map((c) => ({
            id: `omni:case:${c.tenant_id}:${c.id}`,
            label: c.label || c.title,
            hint: c.subtitle ?? `${c.entity_id} · ${c.status}`,
            module: "cases" as ModuleId,
            keywords: `${c.id} ${c.title} ${c.entity_id} ${c.trace_id}`,
            run: () => {
              pinCase({ caseId: c.id, tenantId: c.tenant_id, title: c.title });
              navigate(`/cases/${encodeURIComponent(c.id)}?tenant_id=${encodeURIComponent(c.tenant_id)}`);
              close();
            },
          })),
        });
      }
      if (data.rules.length > 0) {
        sections.push({
          title: "Rules",
          items: data.rules.map((r) => ({
            id: `omni:rule:${r.pack_file}:${r.rule_id}`,
            label: r.label,
            hint: r.subtitle ? `${r.pack_name} · ${r.subtitle}` : r.pack_name,
            module: "rules" as ModuleId,
            keywords: `${r.rule_id} ${r.pack_file} ${r.pack_name}`,
            run: () => {
              const qs = new URLSearchParams({
                pack: r.pack_file,
                rule_id: r.rule_id,
              });
              navigate(`/rules?${qs}`);
              close();
            },
          })),
        });
      }
    }

    const local: CommandItem[] = [];

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
      if (matchesQuery(c, q)) local.push(c);
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
      if (matchesQuery(item, q)) local.push(item);
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
      if (matchesQuery(item, q)) local.push(item);
    }

    const parsed = parseCaseOpenInput(q, workspaceTenantId);
    if (parsed) {
      const alreadyOpen = openCases.some(
        (t) => t.caseId === parsed.caseId && t.tenantId === parsed.tenantId,
      );
      const showOpenRow = !alreadyOpen || q.includes("/");
      if (showOpenRow) {
        local.unshift({
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

    if (local.length > 0) {
      sections.push({ title: "Workspace", items: local });
    }

    return sections;
  }, [
    query,
    debouncedQuery,
    omni,
    openCases,
    navigate,
    close,
    pinCase,
    workspaceTenantId,
    routeCase,
    tenantOnCasePage,
  ]);

  const flatItems = useMemo(() => paletteSections.flatMap((s) => s.items), [paletteSections]);

  const sectionsWithBase = useMemo(() => {
    let base = 0;
    return paletteSections.map((s) => {
      const row = { title: s.title, items: s.items, baseIndex: base };
      base += s.items.length;
      return row;
    });
  }, [paletteSections]);

  useEffect(() => {
    setSelectedIndex((i) => {
      if (flatItems.length === 0) return 0;
      return Math.min(i, flatItems.length - 1);
    });
  }, [flatItems.length]);

  useLayoutEffect(() => {
    if (!listRef.current || flatItems.length === 0) return;
    listRef.current
      .querySelector(`[data-cmd-index="${selectedIndex}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedIndex, flatItems.length, open]);

  const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (flatItems.length === 0) return;
      setSelectedIndex((i) => Math.min(flatItems.length - 1, i + 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (flatItems.length === 0) return;
      setSelectedIndex((i) => Math.max(0, i - 1));
      return;
    }
    if (e.key === "Enter" && flatItems.length > 0) {
      e.preventDefault();
      flatItems[selectedIndex]?.run();
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
            placeholder="Search entities, cases, rules, modules…"
            className="flex-1 min-w-0 bg-transparent text-sm text-gray-100 placeholder:text-gray-600 focus:outline-none py-2"
            aria-label="Search commands"
            aria-controls="command-palette-listbox"
            aria-activedescendant={
              flatItems.length > 0 ? `cmd-opt-${selectedIndex}` : undefined
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
          {flatItems.length === 0 ? (
            <li className="px-4 py-8 text-center text-sm text-gray-500">
              {omniLoading ? "Searching…" : "No matches"}
            </li>
          ) : (
            sectionsWithBase.map((sec) => (
              <Fragment key={sec.title}>
                <li
                  role="presentation"
                  className="px-3 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500 list-none"
                >
                  {sec.title}
                </li>
                {sec.items.map((item, idx) => {
                  const globalIdx = sec.baseIndex + idx;
                  const active = globalIdx === selectedIndex;
                  const domId = `cmd-opt-${globalIdx}`;
                  return (
                    <li key={item.id} role="presentation">
                      <button
                        id={domId}
                        data-cmd-index={globalIdx}
                        type="button"
                        role="option"
                        aria-selected={active}
                        onMouseEnter={() => setSelectedIndex(globalIdx)}
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
                })}
              </Fragment>
            ))
          )}
        </ul>
        <div className="border-t border-surface-800 px-3 py-2 text-[11px] text-gray-600 flex flex-wrap gap-x-3 gap-y-1">
          <span>
            <kbd className="font-mono text-gray-500">↑</kbd>{" "}
            <kbd className="font-mono text-gray-500">↓</kbd> move ·{" "}
            <kbd className="font-mono text-gray-500">↵</kbd> open
          </span>
          <span>
            <kbd className="font-mono text-gray-500">⌘K</kbd> toggle
          </span>
          {query.trim() !== debouncedQuery.trim() ? (
            <span className="text-gray-500">Debouncing…</span>
          ) : null}
          {omniLoading ? <span className="text-gray-500">Searching API…</span> : null}
          {omniError ? <span className="text-amber-600/90 truncate max-w-[220px]">{omniError}</span> : null}
          <span className="hidden sm:inline">Unified search (300ms debounce)</span>
        </div>
      </div>
    </div>
  );
}

/** Toolbar / menu: open the palette without toggling closed. */
export function requestOpenCommandPalette() {
  window.dispatchEvent(new Event("tarka-open-command-palette"));
}
