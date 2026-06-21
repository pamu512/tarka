import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { isCaseWorkbenchTab, type CaseWorkbenchTab } from "../workbench/workbenchContract";

const STORAGE_KEY = "tarka-analyst-open-cases";
const MAX_OPEN_CASES = 14;

export type WorkbenchCommand =
  | { type: "set_tab"; tab: CaseWorkbenchTab }
  | { type: "toggle_copilot"; open?: boolean }
  | { type: "toggle_panel"; panel: string; open?: boolean };

type WorkbenchCommandListener = (cmd: WorkbenchCommand) => void;

export type OpenCaseTab = {
  caseId: string;
  tenantId: string;
  /** Best-effort label; updated when case loads */
  title: string;
};

type StoredShape = { v: 1; tabs: OpenCaseTab[] };

function readStored(): OpenCaseTab[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as StoredShape;
    if (!parsed || parsed.v !== 1 || !Array.isArray(parsed.tabs)) return [];
    return parsed.tabs
      .filter(
        (t) =>
          t &&
          typeof t.caseId === "string" &&
          typeof t.tenantId === "string" &&
          typeof t.title === "string",
      )
      .slice(0, MAX_OPEN_CASES);
  } catch {
    return [];
  }
}

function writeStored(tabs: OpenCaseTab[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ v: 1, tabs }));
  } catch {
    /* ignore quota */
  }
}

type AnalystWorkspaceValue = {
  openCases: OpenCaseTab[];
  /** Tenant from the most recently focused case; used for palette "open by id" default. */
  preferredTenantId: string;
  /** Add or refresh a case tab (most-recent first). Call when opening a case or when title loads. */
  pinCase: (tab: OpenCaseTab) => void;
  removeCase: (caseId: string, tenantId: string) => void;
  clearOpenCases: () => void;
  /** Update title only if tab exists */
  updateCaseTitle: (caseId: string, tenantId: string, title: string) => void;
  /** Subscribe to workbench commands (command palette, hotkeys). Returns unsubscribe. */
  subscribeWorkbenchCommands: (listener: WorkbenchCommandListener) => () => void;
  /** Dispatch a workbench command to active case detail listeners. */
  dispatchWorkbenchCommand: (cmd: WorkbenchCommand) => void;
  /** Build case detail href preserving optional workbench tab. */
  caseDetailHref: (caseId: string, tenantId: string, tab?: CaseWorkbenchTab | null) => string;
};

const AnalystWorkspaceContext = createContext<AnalystWorkspaceValue | null>(null);

export function AnalystWorkspaceProvider({ children }: { children: ReactNode }) {
  const [openCases, setOpenCases] = useState<OpenCaseTab[]>(() =>
    typeof window !== "undefined" ? readStored() : [],
  );
  const [workbenchListeners] = useState(() => new Set<WorkbenchCommandListener>());

  useEffect(() => {
    writeStored(openCases);
  }, [openCases]);

  const pinCase = useCallback((tab: OpenCaseTab) => {
    setOpenCases((prev) => {
      const rest = prev.filter((t) => !(t.caseId === tab.caseId && t.tenantId === tab.tenantId));
      const next = [{ ...tab, title: tab.title || "Case" }, ...rest].slice(0, MAX_OPEN_CASES);
      return next;
    });
  }, []);

  const removeCase = useCallback((caseId: string, tenantId: string) => {
    setOpenCases((prev) => prev.filter((t) => !(t.caseId === caseId && t.tenantId === tenantId)));
  }, []);

  const clearOpenCases = useCallback(() => setOpenCases([]), []);

  const updateCaseTitle = useCallback((caseId: string, tenantId: string, title: string) => {
    setOpenCases((prev) =>
      prev.map((t) =>
        t.caseId === caseId && t.tenantId === tenantId ? { ...t, title } : t,
      ),
    );
  }, []);

  const preferredTenantId = openCases[0]?.tenantId ?? "demo";

  const subscribeWorkbenchCommands = useCallback((listener: WorkbenchCommandListener) => {
    workbenchListeners.add(listener);
    return () => {
      workbenchListeners.delete(listener);
    };
  }, [workbenchListeners]);

  const dispatchWorkbenchCommand = useCallback(
    (cmd: WorkbenchCommand) => {
      for (const listener of workbenchListeners) listener(cmd);
    },
    [workbenchListeners],
  );

  const caseDetailHref = useCallback((caseId: string, tenantId: string, tab?: CaseWorkbenchTab | null) => {
    const q = new URLSearchParams({ tenant_id: tenantId });
    if (tab && tab !== "timeline") q.set("tab", tab);
    return `/cases/${encodeURIComponent(caseId)}?${q}`;
  }, []);

  const value = useMemo(
    () => ({
      openCases,
      preferredTenantId,
      pinCase,
      removeCase,
      clearOpenCases,
      updateCaseTitle,
      subscribeWorkbenchCommands,
      dispatchWorkbenchCommand,
      caseDetailHref,
    }),
    [
      openCases,
      preferredTenantId,
      pinCase,
      removeCase,
      clearOpenCases,
      updateCaseTitle,
      subscribeWorkbenchCommands,
      dispatchWorkbenchCommand,
      caseDetailHref,
    ],
  );

  return (
    <AnalystWorkspaceContext.Provider value={value}>{children}</AnalystWorkspaceContext.Provider>
  );
}

export function useAnalystWorkspace(): AnalystWorkspaceValue {
  const ctx = useContext(AnalystWorkspaceContext);
  if (!ctx) {
    throw new Error("useAnalystWorkspace must be used within AnalystWorkspaceProvider");
  }
  return ctx;
}
