import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams } from 'react-router';
import {
  cases,
  graph,
  type Case,
  type EntityRiskResult,
  type InferenceContext,
  normalizeInferenceContext,
  toUserFacingApiError,
} from "../api/client";
import { decisions } from "../api/v1/decisions";
import { useAnalystWorkspace } from "./AnalystWorkspaceContext";
import {
  DEFAULT_WORKBENCH_PANELS,
  isCaseWorkbenchTab,
  type CaseWorkbenchTab,
  type WorkbenchPanelId,
} from "../workbench/workbenchContract";
import {
  auditCapability,
  calibrationCapability,
  graphCapability,
  initialCapabilityStatus,
  type CapabilityStatus,
} from "../workbench/capabilityStatus";
import { trackPanelUsage, trackWorkbenchEvent, trackWorkbenchTask } from "../workbench/workbenchTelemetry";

const VELOCITY_SPARKLINE_POLL_MS = 15_000;

export type DecisionExplain = {
  score: number;
  decision: string;
  reasons: string[];
  tags: string[];
  rule_hits: string[];
  rule_pack_file?: string | null;
  recommended_action?: string | null;
  inference_context: InferenceContext | null;
  evaluate_payload?: Record<string, unknown> | null;
};

type CaseWorkbenchValue = {
  caseId: string;
  tenantId: string;
  caseData: Case | null;
  loading: boolean;
  error: string | null;
  setError: (v: string | null) => void;
  decisionExplain: DecisionExplain | null;
  graphRisk: EntityRiskResult | null;
  velocityArtifactsUpdatedAt: string | null;
  capabilityStatus: CapabilityStatus;
  calibrationHint: string | null;
  activeTab: CaseWorkbenchTab;
  setActiveTab: (tab: CaseWorkbenchTab) => void;
  copilotRailOpen: boolean;
  setCopilotRailOpen: (open: boolean) => void;
  togglePanel: (panel: WorkbenchPanelId, open?: boolean) => void;
  isPanelOpen: (panel: WorkbenchPanelId) => boolean;
  advancedDevView: boolean;
  setAdvancedDevView: (v: boolean) => void;
  refreshCase: () => Promise<void>;
  refreshVelocityArtifacts: () => Promise<void>;
  bridgeConfirmOpen: boolean;
  setBridgeConfirmOpen: (v: boolean) => void;
  pendingStatusChange: string | null;
  setPendingStatusChange: (v: string | null) => void;
};

const CaseWorkbenchContext = createContext<CaseWorkbenchValue | null>(null);

export function CaseWorkbenchProvider({
  caseId,
  tenantId,
  children,
}: {
  caseId: string;
  tenantId: string;
  children: ReactNode;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { subscribeWorkbenchCommands } = useAnalystWorkspace();
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [decisionExplain, setDecisionExplain] = useState<DecisionExplain | null>(null);
  const [graphRisk, setGraphRisk] = useState<EntityRiskResult | null>(null);
  const [velocityArtifactsUpdatedAt, setVelocityArtifactsUpdatedAt] = useState<string | null>(null);
  const [capabilityStatus, setCapabilityStatus] = useState<CapabilityStatus>(initialCapabilityStatus);
  const [calibrationHint, setCalibrationHint] = useState<string | null>(null);
  const [advancedDevView, setAdvancedDevView] = useState(false);
  const [copilotRailOpen, setCopilotRailOpenState] = useState(false);
  const [panelState, setPanelState] = useState<Record<WorkbenchPanelId, boolean>>(() => ({
    ...DEFAULT_WORKBENCH_PANELS,
  }));
  const [bridgeConfirmOpen, setBridgeConfirmOpen] = useState(false);
  const [pendingStatusChange, setPendingStatusChange] = useState<string | null>(null);

  const tabParam = searchParams.get("tab");
  const activeTab: CaseWorkbenchTab = isCaseWorkbenchTab(tabParam) ? tabParam : "timeline";

  const setActiveTab = useCallback(
    (tab: CaseWorkbenchTab) => {
      trackWorkbenchEvent({ kind: "tab_change", tab, caseId, tenantId });
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          if (tab === "timeline") n.delete("tab");
          else n.set("tab", tab);
          return n;
        },
        { replace: true },
      );
    },
    [caseId, tenantId, setSearchParams],
  );

  const setCopilotRailOpen = useCallback(
    (open: boolean) => {
      setCopilotRailOpenState(open);
      trackPanelUsage("copilot_rail", open, { caseId, tenantId });
    },
    [caseId, tenantId],
  );

  const togglePanel = useCallback(
    (panel: WorkbenchPanelId, open?: boolean) => {
      setPanelState((prev) => {
        const nextOpen = open ?? !prev[panel];
        trackPanelUsage(panel, nextOpen, { caseId, tenantId });
        return { ...prev, [panel]: nextOpen };
      });
    },
    [caseId, tenantId],
  );

  const isPanelOpen = useCallback((panel: WorkbenchPanelId) => panelState[panel], [panelState]);

  const fetchCase = useCallback(async () => {
    if (!caseId) return;
    try {
      const data = await cases.get(caseId, tenantId);
      setCaseData(data);
      setError(null);
    } catch (e) {
      setError(toUserFacingApiError(e, { subject: "Case detail", action: "load this case" }));
    } finally {
      setLoading(false);
    }
  }, [caseId, tenantId]);

  const refreshCase = useCallback(async () => {
    await fetchCase();
    trackWorkbenchTask("case_refresh", { caseId, tenantId });
  }, [fetchCase, caseId, tenantId]);

  const refreshVelocityArtifacts = useCallback(async () => {
    if (!caseData) return;
    const hasTrace = Boolean(caseData.trace_id?.trim());
    let auditOk = false;
    try {
      if (hasTrace) {
        const audit = await decisions.getAudit(caseData.trace_id, caseData.tenant_id, {
          detail_level: "analyst",
        });
        setDecisionExplain({
          score: audit.score,
          decision: audit.decision,
          reasons: audit.reasons || [],
          tags: audit.tags || [],
          rule_hits: audit.rule_hits || [],
          rule_pack_file: audit.rule_pack_file ?? null,
          recommended_action: audit.recommended_action ?? null,
          inference_context: normalizeInferenceContext(audit.inference_context),
          evaluate_payload: audit.evaluate_payload ?? null,
        });
        setVelocityArtifactsUpdatedAt(new Date().toISOString());
        auditOk = true;
      } else {
        setDecisionExplain(null);
        setVelocityArtifactsUpdatedAt(null);
      }
    } catch {
      setDecisionExplain(null);
      auditOk = false;
    }

    let graphOk = false;
    try {
      const risk = await graph.entityRisk(caseData.entity_id, caseData.tenant_id);
      setGraphRisk(risk);
      graphOk = true;
    } catch {
      setGraphRisk(null);
      graphOk = false;
    }

    let calOk = false;
    let calHealthy: boolean | null = null;
    let calHint: string | null = null;
    try {
      const bins = await decisions.reliabilityBins(caseData.tenant_id, 2000, 10);
      calOk = true;
      const posture = bins.posture;
      calHealthy = posture?.healthy ?? null;
      calHint =
        posture?.healthy === false
          ? String(posture.hint || posture.status || "insufficient labels")
          : posture?.healthy === true
            ? "healthy"
            : null;
    } catch {
      calOk = false;
      calHint = null;
    }

    setCalibrationHint(calHint);
    setCapabilityStatus({
      audit: auditCapability(hasTrace, hasTrace ? auditOk : null),
      graph: graphCapability(graphOk),
      calibration: calibrationCapability(calOk, calHealthy),
    });
  }, [caseData]);

  useEffect(() => {
    setLoading(true);
    void fetchCase();
  }, [fetchCase]);

  useEffect(() => {
    void refreshVelocityArtifacts();
  }, [refreshVelocityArtifacts]);

  useEffect(() => {
    if (!caseData?.trace_id) return undefined;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshVelocityArtifacts();
    }, VELOCITY_SPARKLINE_POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") void refreshVelocityArtifacts();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [caseData?.trace_id, refreshVelocityArtifacts]);

  useEffect(() => {
    return subscribeWorkbenchCommands((cmd) => {
      if (cmd.type === "set_tab" && isCaseWorkbenchTab(cmd.tab)) {
        setActiveTab(cmd.tab);
      } else if (cmd.type === "toggle_copilot") {
        setCopilotRailOpenState((prev) => cmd.open ?? !prev);
      } else if (cmd.type === "toggle_panel") {
        const panel = cmd.panel as WorkbenchPanelId;
        if (panel in DEFAULT_WORKBENCH_PANELS) {
          togglePanel(panel, cmd.open);
        }
      }
    });
  }, [subscribeWorkbenchCommands, setActiveTab, togglePanel]);

  const value = useMemo(
    (): CaseWorkbenchValue => ({
      caseId,
      tenantId,
      caseData,
      loading,
      error,
      setError,
      decisionExplain,
      graphRisk,
      velocityArtifactsUpdatedAt,
      capabilityStatus,
      calibrationHint,
      activeTab,
      setActiveTab,
      copilotRailOpen,
      setCopilotRailOpen,
      togglePanel,
      isPanelOpen,
      advancedDevView,
      setAdvancedDevView,
      refreshCase,
      refreshVelocityArtifacts,
      bridgeConfirmOpen,
      setBridgeConfirmOpen,
      pendingStatusChange,
      setPendingStatusChange,
    }),
    [
      caseId,
      tenantId,
      caseData,
      loading,
      error,
      decisionExplain,
      graphRisk,
      velocityArtifactsUpdatedAt,
      capabilityStatus,
      calibrationHint,
      activeTab,
      setActiveTab,
      copilotRailOpen,
      setCopilotRailOpen,
      togglePanel,
      isPanelOpen,
      advancedDevView,
      refreshCase,
      refreshVelocityArtifacts,
      bridgeConfirmOpen,
      pendingStatusChange,
    ],
  );

  return <CaseWorkbenchContext.Provider value={value}>{children}</CaseWorkbenchContext.Provider>;
}

export function useCaseWorkbench(): CaseWorkbenchValue {
  const ctx = useContext(CaseWorkbenchContext);
  if (!ctx) {
    throw new Error("useCaseWorkbench must be used within CaseWorkbenchProvider");
  }
  return ctx;
}
