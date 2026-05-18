import { lazy, Suspense, useEffect, useState, useRef, useCallback, useMemo } from "react";
import { Link, useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useAnalystWorkspace } from "../context/AnalystWorkspaceContext";
import { useRegisterPageMeta } from "../context/PageMetaContext";
import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { useToast } from "../context/ToastContext";
import {
  cases,
  decisions,
  graph,
  type Case,
  type EntityRiskResult,
  type GraphEdge,
  type GraphNode,
  type InferenceContext,
  normalizeInferenceContext,
  type SubgraphResponse,
} from "../api/client";
import StatusBadge from "../components/StatusBadge";
import PriorityBadge from "../components/PriorityBadge";
import { PageTitle } from "../components/PageTitle";
import { parseGraphSnapshot, SnapshotGraph } from "../components/CaseView/SnapshotGraph";
import { clusterSubgraphByDeviceHash, DEVICE_CLUSTER_GRAPH_LABEL } from "../utils/entityDeviceClustering";
import { TimeTravelSlider } from "../components/CaseView/TimeTravelSlider";
import { TuneRuleModal } from "../components/CaseView/TuneRuleModal";
import { TriageHeader, type TriageFlashCard } from "../components/CaseView/TriageHeader";
import {
  ExternalSignalHoverBody,
  GeoHoverBody,
  GraphMetricHoverBody,
  InferenceColocationHoverBody,
  InferenceGeoConsistencyHoverBody,
  InferenceImpossibleTravelHoverBody,
  InferenceIntegrityHoverBody,
  InferenceNetworkTrustHoverBody,
  InferenceReplayHoverBody,
  InferenceTamperHoverBody,
  QueueScoreHoverBody,
  VelocityHoverBody,
} from "../components/CaseView/MetricHoverPanels";
import { InfoHover } from "../components/InfoHover";
import { GraphContextPanel } from "../components/GraphContextPanel";
import { FraudScoreTrack } from "../components/FraudScoreTrack";
import { InferenceMetricTrack } from "../components/InferenceMetricTrack";
import { SarManagementPanel } from "../components/SarManagementPanel";
import { KycHandoverPanel } from "../components/compliance/KycHandoverPanel";
import { EntityProfileSparklines } from "../components/CaseView/EntityProfileSparklines";
import { SaarthiFeatureImportancePanel } from "../components/CaseView/SaarthiFeatureImportancePanel";
import { buildSaarthiFeatureImportanceRequest } from "../lib/saarthi/featureImportance";
import { VelocityHeatmap } from "../components/CaseView/VelocityHeatmap";

const GeographicCollisionMap = lazy(() =>
  import("../components/CaseView/GeographicCollisionMap").then((m) => ({ default: m.GeographicCollisionMap })),
);
import { SupportIdHint } from "../components/SupportIdHint";
import { buildCaseComparisonHref } from "../utils/caseComparisonUrl";
import { toUserFacingError } from "../utils/userFacingErrors";
import {
  buildCaseWorkspaceEvidencePdfBlob,
  buildCaseWorkspaceEvidenceSnapshot,
  caseEvidenceExportPdfFilename,
} from "../utils/evidenceExportPdf";
import { loadGraphAnnotations, setGraphNodeAnnotation } from "../utils/graphNodeAnnotations";
import { GraphAnnotationPopover } from "../components/CaseView/GraphAnnotationPopover";
import {
  KnowledgeGraphDesktopRail,
  KnowledgeGraphMobilePanel,
  useKnowledgeGraphSidebarState,
} from "../components/CaseView/KnowledgeGraphSidebar";
import { ShadowChatSidebar } from "../components/CaseView/ShadowChatSidebar";
import { isHeroHotkeyEventIgnored } from "../utils/heroHotkeys";
import { Network, type Options } from "vis-network";
import { DataSet } from "vis-data";

const CASE_DETAIL_TABS = ["timeline", "audit", "graph"] as const;

/** Re-fetch decision audit + graph risk for velocity sparklines (Prompt 164). */
const VELOCITY_SPARKLINE_POLL_MS = 15_000;
type Tab = (typeof CASE_DETAIL_TABS)[number];

function isCaseDetailTab(v: string | null): v is Tab {
  return v != null && (CASE_DETAIL_TABS as readonly string[]).includes(v);
}

const RECOMMENDED_ACTION_LABELS: Record<string, string> = {
  block: "Block this activity",
  manual_review: "Manual review recommended",
  step_up_mfa: "Step up authentication (MFA)",
  step_up_attestation: "Request stronger device or session proof",
  allow: "Allow — continue monitoring",
  deny: "Deny — stop or escalate per policy",
  review: "Review before proceeding",
};

function humanizeRecommendedAction(code: string): string {
  const c = code.trim();
  return RECOMMENDED_ACTION_LABELS[c] ?? c.replace(/_/g, " ");
}

/** First clause for the sight-layer “why” line (Saarthi / ML summary). */
function firstSightSentence(text: string): string {
  const t = text.trim();
  if (!t) return "";
  const split = t.split(/(?<=[.!?])\s+/);
  const one = (split[0] ?? t).trim();
  return one.length > 220 ? `${one.slice(0, 217)}…` : one;
}

/** Scan-layer flash cards: Velocity, Graph, Geo-inconsistency proxy. */
function buildTriageFlashCards(
  ctx: InferenceContext | null,
  graphRisk: EntityRiskResult | null,
): [TriageFlashCard, TriageFlashCard, TriageFlashCard] {
  const velocity: TriageFlashCard = !ctx
    ? { title: "Velocity", value: "—", tone: "neutral" }
    : ctx.velocity_events_24h >= 40
      ? { title: "Velocity", value: "High", tone: "critical" }
      : ctx.velocity_events_24h >= 12
        ? { title: "Velocity", value: "Elevated", tone: "warn" }
        : { title: "Velocity", value: "Normal", tone: "ok" };

  let graph: TriageFlashCard;
  if (!graphRisk) {
    graph = { title: "Graph", value: "—", tone: "neutral" };
  } else {
    const rs = graphRisk.risk_score;
    const factorHit = graphRisk.risk_factors?.find((f) => /mule|ring|sybil|farm/i.test(f)) ?? null;
    if (rs >= 0.65) {
      graph = {
        title: "Graph",
        value: factorHit ?? "Mule ring",
        tone: "critical",
      };
    } else if (rs >= 0.35) {
      graph = { title: "Graph", value: "Elevated", tone: "warn" };
    } else {
      graph = { title: "Graph", value: "Low linkage", tone: "ok" };
    }
  }

  const geo: TriageFlashCard = !ctx
    ? { title: "Geo", value: "—", tone: "neutral" }
    : ctx.impossible_travel_risk > 0.35 || ctx.geo_consistency_risk > 0.55
      ? { title: "Geo", value: "Inconsistent", tone: "critical" }
      : ctx.geo_consistency_risk > 0.22
        ? { title: "Geo", value: "Suspect", tone: "warn" }
        : { title: "Geo", value: "Consistent", tone: "ok" };

  return [velocity, graph, geo];
}

type DecisionExplain = {
  score: number;
  decision: string;
  reasons: string[];
  tags: string[];
  rule_hits: string[];
  recommended_action?: string | null;
  inference_context: InferenceContext | null;
  /** Present when audit is loaded with analyst/full detail — transaction envelope for exposure hints. */
  evaluate_payload?: Record<string, unknown> | null;
};

/** Best-effort parse of evaluate payload / nested envelopes for triage financial hints (DuckDB cohort rolls up same trace keys when wired). */
function extractTransactionMoney(payload: Record<string, unknown> | null | undefined): {
  amount: number;
  currency: string;
} | null {
  if (!payload || typeof payload !== "object") return null;
  const tryAmount = (obj: Record<string, unknown>): { amount: number; currency: string } | null => {
    const currency = String(obj.currency ?? obj.currency_code ?? obj.asset ?? "USD");
    for (const key of ["amount", "transaction_amount", "usd_amount", "value", "notional"]) {
      const v = obj[key];
      if (typeof v === "number" && Number.isFinite(v)) return { amount: v, currency };
    }
    return null;
  };
  const direct = tryAmount(payload);
  if (direct) return direct;
  for (const nk of ["transaction", "payload", "event", "body"]) {
    const inner = payload[nk];
    if (inner && typeof inner === "object" && !Array.isArray(inner)) {
      const got = tryAmount(inner as Record<string, unknown>);
      if (got) return got;
    }
  }
  return null;
}

export default function CaseDetail() {
  const { caseId } = useParams<{ caseId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { tenantId: workspaceTenantId } = useTenantEnvironment();
  const tenantEffective = (searchParams.get("tenant_id")?.trim() || workspaceTenantId || "demo").trim();
  const navigate = useNavigate();
  const { pinCase } = useAnalystWorkspace();
  const { toast } = useToast();
  const [advancedDevView, setAdvancedDevView] = useState(false);
  const [shadowChatOpen, setShadowChatOpen] = useState(false);
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const tabParam = searchParams.get("tab");
  const activeTab: Tab = isCaseDetailTab(tabParam) ? tabParam : "timeline";

  const setActiveTab = useCallback(
    (tab: Tab) => {
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
    [setSearchParams],
  );
  const [commentText, setCommentText] = useState("");
  const [commentSubmitting, setCommentSubmitting] = useState(false);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [labelInput, setLabelInput] = useState("");
  const [decisionExplain, setDecisionExplain] = useState<DecisionExplain | null>(null);
  const [graphRisk, setGraphRisk] = useState<EntityRiskResult | null>(null);
  const [bundleBusy, setBundleBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [tuneRuleOpen, setTuneRuleOpen] = useState(false);
  const [velocityArtifactsUpdatedAt, setVelocityArtifactsUpdatedAt] = useState<string | null>(null);

  const fetchCase = useCallback(async () => {
    if (!caseId) return;
    try {
      const data = await cases.get(caseId, tenantEffective);
      setCaseData(data);
      setError(null);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Case detail", action: "load this case" }));
    } finally {
      setLoading(false);
    }
  }, [caseId, tenantEffective]);

  const pageMeta = useMemo(
    () =>
      caseData
        ? { title: caseData.title, subtitle: `${caseData.tenant_id} · ${caseData.id.slice(0, 12)}…` }
        : null,
    [caseData],
  );
  useRegisterPageMeta(pageMeta);

  useEffect(() => {
    fetchCase();
  }, [fetchCase]);

  useEffect(() => {
    if (!caseData) return;
    pinCase({
      caseId: caseData.id,
      tenantId: caseData.tenant_id,
      title: caseData.title || "Case",
    });
  }, [caseData, pinCase]);

  const refreshVelocityArtifacts = useCallback(async () => {
    if (!caseData) return;
    try {
      if (caseData.trace_id) {
        const audit = await decisions.getAudit(caseData.trace_id, caseData.tenant_id, {
          detail_level: "analyst",
        });
        setDecisionExplain({
          score: audit.score,
          decision: audit.decision,
          reasons: [],
          tags: audit.tags || [],
          rule_hits: audit.rule_hits || [],
          recommended_action: audit.recommended_action ?? null,
          inference_context: normalizeInferenceContext(audit.inference_context),
          evaluate_payload: audit.evaluate_payload ?? null,
        });
        setVelocityArtifactsUpdatedAt(new Date().toISOString());
      } else {
        setDecisionExplain(null);
        setVelocityArtifactsUpdatedAt(null);
      }
    } catch {
      setDecisionExplain(null);
    }
    try {
      const risk = await graph.entityRisk(caseData.entity_id, caseData.tenant_id);
      setGraphRisk(risk);
    } catch {
      setGraphRisk(null);
    }
  }, [caseData]);

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

  const handleStatusChange = async (newStatus: string) => {
    if (!caseId || !caseData || statusUpdating) return;
    setStatusUpdating(true);
    try {
      const updated = await cases.update(caseId, caseData.tenant_id, { status: newStatus as Case["status"] });
      setCaseData(updated);
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Case status", action: "update case status" }));
    } finally {
      setStatusUpdating(false);
    }
  };

  const handlePriorityChange = async (newPriority: string) => {
    if (!caseId || !caseData) return;
    try {
      const updated = await cases.update(caseId, caseData.tenant_id, { priority: newPriority as Case["priority"] });
      setCaseData(updated);
    } catch (e) {
      toast(toUserFacingError(e, { subject: "Case priority", action: "update case priority" }), "error");
    }
  };

  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!caseId || !caseData || !commentText.trim()) return;
    setCommentSubmitting(true);
    try {
      await cases.addComment(caseId, caseData.tenant_id, "analyst", commentText.trim());
      await fetchCase();
      setCommentText("");
    } catch (err) {
      setError(toUserFacingError(err, { subject: "Case comment", action: "add a case comment" }));
    } finally {
      setCommentSubmitting(false);
    }
  };

  const handleDownloadEvidenceBundle = async () => {
    if (!caseId || !caseData) return;
    setBundleBusy(true);
    try {
      const bundle = await cases.evidenceBundle(caseId, caseData.tenant_id);
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `evidence-bundle-${caseId.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast("Evidence bundle downloaded", "success");
    } catch (e) {
      toast(toUserFacingError(e, { subject: "Evidence bundle", action: "download evidence bundle" }), "error");
    } finally {
      setBundleBusy(false);
    }
  };

  const handleEvidenceExportPdf = useCallback(() => {
    if (!caseData) return;
    setPdfBusy(true);
    try {
      const ctx = decisionExplain?.inference_context ?? null;
      const [v, g, geo] = buildTriageFlashCards(ctx, graphRisk);
      const flashPlain = [
        { title: v.title, value: v.value },
        { title: g.title, value: g.value },
        { title: geo.title, value: geo.value },
      ];
      const fm = extractTransactionMoney(decisionExplain?.evaluate_payload ?? undefined);
      let financialLine: string | null = null;
      if (fm) {
        financialLine = `Exposure (audit envelope): ${new Intl.NumberFormat(undefined, {
          style: "currency",
          currency: fm.currency,
          maximumFractionDigits: 2,
        }).format(fm.amount)}`;
      }
      const vel =
        ctx != null && Number.isFinite(ctx.velocity_events_24h) ? ctx.velocity_events_24h : null;
      const qs =
        caseData.queue_score != null && Number.isFinite(caseData.queue_score)
          ? caseData.queue_score
          : null;
      const rawGr =
        graphRisk != null ? graphRisk.risk_score : ctx != null ? ctx.graph_risk_score : null;
      const graphRiskDisplay =
        rawGr != null && Number.isFinite(rawGr) ? rawGr.toFixed(3) : null;

      const sightForPdf = (() => {
        const ml = decisionExplain?.inference_context?.ml_summary?.trim();
        if (ml) return firstSightSentence(ml);
        const ra = decisionExplain?.recommended_action?.trim();
        if (ra) return humanizeRecommendedAction(ra);
        return null;
      })();

      const slaDeadlinePdf = new Date(caseData.sla_deadline ?? caseData.created_at);
      const slaOnTrackPdf = slaDeadlinePdf >= new Date();

      const snapshot = buildCaseWorkspaceEvidenceSnapshot({
        caseData,
        activeTab,
        slaOnTrack: slaOnTrackPdf,
        sightLine: sightForPdf,
        flashCardsPlain: flashPlain,
        financialLine,
        velocity24h: vel,
        queueScore: qs,
        graphRiskDisplay,
        decisionExplain: decisionExplain
          ? {
              score: decisionExplain.score,
              decision: decisionExplain.decision,
              tags: decisionExplain.tags,
              rule_hits: decisionExplain.rule_hits,
              recommended_action: decisionExplain.recommended_action,
              inference_context: decisionExplain.inference_context,
            }
          : null,
        graphRisk,
      });
      const blob = buildCaseWorkspaceEvidencePdfBlob(snapshot);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = caseEvidenceExportPdfFilename(caseData.id);
      a.click();
      URL.revokeObjectURL(url);
      toast("Evidence PDF downloaded", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not build evidence PDF", "error");
    } finally {
      setPdfBusy(false);
    }
  }, [caseData, activeTab, decisionExplain, graphRisk, toast]);

  const handleAddLabel = async () => {
    if (!caseId || !caseData || !labelInput.trim()) return;
    try {
      await cases.addLabels(caseId, caseData.tenant_id, [labelInput.trim()]);
      await fetchCase();
      setLabelInput("");
    } catch (e) {
      toast(toUserFacingError(e, { subject: "Case label", action: "add a case label" }), "error");
    }
  };

  const heroApprove = useCallback(async () => {
    if (!caseId || !caseData || statusUpdating) return;
    if (caseData.status !== "open") {
      toast("A · Approve moves Open cases to Investigating.", "info");
      return;
    }
    setStatusUpdating(true);
    try {
      const updated = await cases.update(caseId, caseData.tenant_id, { status: "investigating" });
      setCaseData(updated);
      toast("Approved — Investigating.", "success");
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Case status", action: "approve case" }));
    } finally {
      setStatusUpdating(false);
    }
  }, [caseId, caseData, statusUpdating, toast]);

  const heroReject = useCallback(async () => {
    if (!caseId || !caseData || statusUpdating) return;
    if (caseData.status === "closed") {
      toast("Case is already closed.", "info");
      return;
    }
    setStatusUpdating(true);
    try {
      const updated = await cases.update(caseId, caseData.tenant_id, { status: "closed" });
      setCaseData(updated);
      toast("Rejected — case closed.", "success");
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Case status", action: "close case" }));
    } finally {
      setStatusUpdating(false);
    }
  }, [caseId, caseData, statusUpdating, toast]);

  const heroGoShadow = useCallback(() => {
    if (!caseData) return;
    pinCase({
      caseId: caseData.id,
      tenantId: caseData.tenant_id,
      title: caseData.title || "Case",
    });
    setShadowChatOpen(true);
  }, [caseData, pinCase]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isHeroHotkeyEventIgnored(e)) return;
      const k = e.key.toLowerCase();
      if (k !== "a" && k !== "r" && k !== "s") return;
      e.preventDefault();
      if (k === "s") heroGoShadow();
      else if (k === "a") void heroApprove();
      else void heroReject();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [heroApprove, heroReject, heroGoShadow]);

  const knowledgeGraphState = useKnowledgeGraphSidebarState(
    caseData?.entity_id ?? "",
    caseData?.tenant_id ?? "",
    Boolean(caseData?.entity_id && caseData?.tenant_id),
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error && !caseData) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-3">
          <p className="text-red-400">{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center justify-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
          <button
            onClick={() => navigate("/cases")}
            className="px-4 py-2 text-sm text-brand-400 hover:text-brand-300"
          >
            Back to Cases
          </button>
        </div>
      </div>
    );
  }

  if (!caseData) return null;

  const slaDeadline = new Date(caseData.sla_deadline ?? caseData.created_at);
  const slaPassed = slaDeadline < new Date();

  const casesListHref = `/cases?tenant_id=${encodeURIComponent(caseData.tenant_id)}`;

  const financialMoney = useMemo(
    () => extractTransactionMoney(decisionExplain?.evaluate_payload ?? undefined),
    [decisionExplain?.evaluate_payload],
  );

  const saarthiFeatureImportancePayload = useMemo(() => {
    if (!caseData?.trace_id || !decisionExplain) return null;
    return buildSaarthiFeatureImportanceRequest({
      traceId: caseData.trace_id,
      tenantId: caseData.tenant_id,
      entityId: caseData.entity_id,
      score: decisionExplain.score,
      decision: decisionExplain.decision,
      inference: decisionExplain.inference_context,
      ruleHits: decisionExplain.rule_hits,
      tags: decisionExplain.tags,
    });
  }, [caseData, decisionExplain]);

  const saarthiFeatureImportanceKey = useMemo(() => {
    if (!caseData?.trace_id || !decisionExplain) return "";
    return `${caseData.trace_id}:${decisionExplain.score}:${decisionExplain.decision}:${velocityArtifactsUpdatedAt ?? ""}`;
  }, [caseData?.trace_id, decisionExplain, velocityArtifactsUpdatedAt]);

  const triageFlashCards = useMemo((): [
    TriageFlashCard,
    TriageFlashCard,
    TriageFlashCard,
  ] => {
    const ctx = decisionExplain?.inference_context ?? null;
    const [velocity, graph, geo] = buildTriageFlashCards(ctx, graphRisk);
    return [
      { ...velocity, hoverDetail: <VelocityHoverBody ctx={ctx} /> },
      { ...graph, hoverDetail: <GraphMetricHoverBody risk={graphRisk} inference={ctx} /> },
      { ...geo, hoverDetail: <GeoHoverBody ctx={ctx} /> },
    ];
  }, [decisionExplain?.inference_context, graphRisk]);

  const sightLine = useMemo(() => {
    const ml = decisionExplain?.inference_context?.ml_summary?.trim();
    if (ml) return firstSightSentence(ml);
    const ra = decisionExplain?.recommended_action?.trim();
    if (ra) return humanizeRecommendedAction(ra);
    return null;
  }, [decisionExplain?.inference_context?.ml_summary, decisionExplain?.recommended_action]);

  return (
    <div className="flex min-h-0 w-full flex-col xl:flex-row xl:items-stretch xl:min-h-[calc(100vh-10rem)]">
      <div className="min-w-0 flex-1 space-y-6 animate-fade-in p-6">
      <nav className="text-sm text-gray-500 flex flex-wrap items-center gap-2" aria-label="Breadcrumb">
        <Link to={casesListHref} className="text-brand-400 hover:text-brand-300">
          Cases
        </Link>
        <span aria-hidden>/</span>
        <span className="text-gray-300 truncate min-w-0 max-w-[min(100%,32rem)]">{caseData.title}</span>
      </nav>

      <KnowledgeGraphMobilePanel
        entityId={caseData.entity_id}
        tenantId={caseData.tenant_id}
        state={knowledgeGraphState}
      />

      {error ? (
        <div className="rounded-lg border border-rose-500/35 bg-rose-500/10 px-3 py-2 text-sm text-rose-300 space-y-1">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center gap-2 text-[11px] text-rose-200/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-rose-400/35 hover:border-rose-300/50 hover:text-rose-100 transition-colors"
          />
        </div>
      ) : null}

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2 min-w-0 flex-1">
          <PageTitle module="cases">{caseData.title}</PageTitle>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-gray-400 font-mono">{caseData.id}</span>
            <StatusBadge status={caseData.status} />
            <PriorityBadge priority={caseData.priority} />
            <span
              className={`text-xs font-medium px-2 py-1 rounded-full ${
                slaPassed ? "bg-red-500/20 text-red-400" : "bg-green-500/20 text-green-400"
              }`}
            >
              SLA: {slaPassed ? "Breached" : "On Track"}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 self-start">
          <Link
            to={buildCaseComparisonHref({ tenantId: caseData.tenant_id, caseA: caseData.id })}
            className="shrink-0 text-xs font-semibold px-3 py-2 rounded-lg border border-brand-500/35 bg-brand-600/15 text-brand-200 hover:bg-brand-600/25 transition-colors"
          >
            Compare cases
          </Link>
          <button
            type="button"
            disabled={pdfBusy}
            onClick={() => handleEvidenceExportPdf()}
            title="Download a sanitized PDF snapshot of this case workspace (active tab, triage, and comments) for legal or compliance"
            className="shrink-0 text-xs font-semibold px-3 py-2 rounded-lg border transition-colors border-emerald-500/35 bg-emerald-950/35 text-emerald-100 hover:bg-emerald-950/55 disabled:opacity-45 disabled:cursor-wait"
          >
            {pdfBusy ? "Preparing PDF…" : "Evidence export (PDF)"}
          </button>
          <button
            type="button"
            aria-pressed={shadowChatOpen}
            onClick={() => setShadowChatOpen((v) => !v)}
            className={`shrink-0 text-xs font-semibold px-3 py-2 rounded-lg border transition-colors ${
              shadowChatOpen
                ? "border-brand-500/50 bg-brand-500/15 text-brand-200"
                : "border-surface-600 bg-surface-800 text-gray-300 hover:bg-surface-700"
            }`}
          >
            {shadowChatOpen ? "Shadow AI: open" : "Shadow AI"}
          </button>
          <button
            type="button"
            aria-pressed={advancedDevView}
            onClick={() => setAdvancedDevView((v) => !v)}
            className={`shrink-0 text-xs font-semibold px-3 py-2 rounded-lg border transition-colors ${
              advancedDevView
                ? "border-brand-500/50 bg-brand-500/15 text-brand-200"
                : "border-surface-600 bg-surface-800 text-gray-300 hover:bg-surface-700"
            }`}
          >
            {advancedDevView ? "Advanced / Dev View: on" : "Advanced / Dev View"}
          </button>
        </div>
      </div>

      <p className="text-[11px] text-gray-500 flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Keyboard shortcuts">
        <span className="text-gray-600 uppercase tracking-wide font-semibold">Hero keys</span>
        <span>
          <kbd className="px-1.5 py-0.5 rounded border border-surface-600 bg-surface-900 font-mono text-[10px] text-gray-300">
            A
          </kbd>{" "}
          Approve (Open → Investigating)
        </span>
        <span>
          <kbd className="px-1.5 py-0.5 rounded border border-surface-600 bg-surface-900 font-mono text-[10px] text-gray-300">
            R
          </kbd>{" "}
          Reject (Close case)
        </span>
        <span>
          <kbd className="px-1.5 py-0.5 rounded border border-surface-600 bg-surface-900 font-mono text-[10px] text-gray-300">
            S
          </kbd>{" "}
          Shadow AI chat (sidebar)
        </span>
      </p>

      <p className="text-[11px] text-gray-500">
        <Link
          to={`/rules?tenant_id=${encodeURIComponent(caseData.tenant_id)}&trace_id=${encodeURIComponent(caseData.trace_id)}`}
          className="text-brand-400 hover:text-brand-300 font-medium"
        >
          Rule Sandbox
        </Link>
        <span className="text-gray-600">
          {" "}
          — dry-run draft JSON rules against this case&apos;s stored audit payload before deploying to Rust.
        </span>
      </p>

      <TriageHeader
        verdict={decisionExplain?.decision ?? "review"}
        riskScore={decisionExplain?.score ?? 0}
        flashCards={triageFlashCards}
        saarthiLine={sightLine}
      />

      <EntityProfileSparklines
        entityId={caseData.entity_id}
        inference={decisionExplain?.inference_context ?? null}
        anchorIso={caseData.updated_at ?? caseData.created_at}
        cohortSpend={financialMoney}
        lastUpdatedIso={velocityArtifactsUpdatedAt}
      />

      <VelocityHeatmap
        inference={decisionExplain?.inference_context ?? null}
        anchorIso={caseData.updated_at ?? caseData.created_at}
      />

      <SaarthiFeatureImportancePanel
        requestKey={saarthiFeatureImportanceKey}
        payload={saarthiFeatureImportancePayload}
      />

      <Suspense
        fallback={
          <div
            className="rounded-xl border border-surface-700 bg-surface-950/50 min-h-[320px] animate-pulse"
            aria-busy
            aria-label="Loading geographic map"
          />
        }
      >
        <GeographicCollisionMap evaluatePayload={decisionExplain?.evaluate_payload ?? null} />
      </Suspense>

      {/* Triage workspace — rigid 12-column-style grid (collapses to single column < xl) */}
      <section
        aria-label="Case triage workspace"
        className="grid gap-4 grid-cols-1 min-w-0 xl:grid-cols-12 xl:gap-x-4 xl:gap-y-0"
      >
        {/* Financial impact (DuckDB / analytics plane) */}
        <div className="xl:col-span-3 bg-surface-900 border border-surface-700 rounded-xl p-4 flex flex-col min-h-[8rem]">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">
            Financial impact (DuckDB cohort)
          </h3>
          {financialMoney ? (
            <p className="text-2xl font-semibold text-gray-100 tabular-nums">
              {new Intl.NumberFormat(undefined, {
                style: "currency",
                currency: financialMoney.currency,
                maximumFractionDigits: 2,
              }).format(financialMoney.amount)}
            </p>
          ) : (
            <p className="text-sm text-gray-400 leading-snug">
              No transaction amount on the audit envelope. Rollups appear when the analytics plane attaches DuckDB cohort
              metrics for this trace.
            </p>
          )}
          <dl className="mt-auto pt-4 grid grid-cols-2 gap-x-3 gap-y-2 text-xs border-t border-surface-700">
            <div>
              <dt className="text-gray-500">Velocity (24h events)</dt>
              <dd className="text-gray-200 font-mono tabular-nums">
                {decisionExplain?.inference_context != null ? (
                  <InfoHover
                    heading="Velocity (24h events)"
                    detail={<VelocityHoverBody ctx={decisionExplain.inference_context} />}
                  >
                    {decisionExplain.inference_context.velocity_events_24h}
                  </InfoHover>
                ) : (
                  "—"
                )}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Queue score</dt>
              <dd className="text-gray-200 font-mono tabular-nums">
                <InfoHover heading="Queue score" detail={<QueueScoreHoverBody score={caseData.queue_score} />}>
                  {caseData.queue_score != null ? caseData.queue_score.toFixed(1) : "—"}
                </InfoHover>
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Graph risk (0–1)</dt>
              <dd className="text-gray-200 font-mono tabular-nums">
                {(() => {
                  const raw =
                    graphRisk != null
                      ? graphRisk.risk_score
                      : decisionExplain?.inference_context != null
                        ? decisionExplain.inference_context.graph_risk_score
                        : null;
                  if (raw == null || !Number.isFinite(raw)) return "—";
                  return (
                    <InfoHover
                      heading="Graph risk (0–1)"
                      detail={
                        <GraphMetricHoverBody
                          risk={graphRisk}
                          inference={decisionExplain?.inference_context ?? null}
                        />
                      }
                    >
                      {raw.toFixed(3)}
                    </InfoHover>
                  );
                })()}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Community size</dt>
              <dd className="text-gray-200 font-mono tabular-nums">
                {graphRisk ? (
                  <InfoHover
                    heading="Community size"
                    detail={
                      <GraphMetricHoverBody
                        risk={graphRisk}
                        inference={decisionExplain?.inference_context ?? null}
                      />
                    }
                  >
                    {graphRisk.community_size}
                  </InfoHover>
                ) : (
                  "—"
                )}
              </dd>
            </div>
          </dl>
        </div>

        {/* AI summary — analyst-readable only */}
        <div className="xl:col-span-6 bg-surface-900 border border-surface-700 rounded-xl p-4 flex flex-col min-h-[8rem]">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">AI summary</h3>
          {decisionExplain?.recommended_action ? (
            <div className="rounded-lg border border-amber-500/35 bg-amber-500/[0.08] px-3 py-2 mb-3">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-amber-200/90">
                Recommended next step
              </div>
              <p className="text-base font-semibold text-gray-50 leading-snug">
                {humanizeRecommendedAction(decisionExplain.recommended_action)}
              </p>
              {advancedDevView ? (
                <code className="mt-2 block text-[11px] text-gray-400 font-mono bg-surface-950/50 rounded px-2 py-1">
                  {decisionExplain.recommended_action}
                </code>
              ) : null}
            </div>
          ) : null}
          {decisionExplain ? (
            <>
              <div className="rounded-lg border border-surface-700/80 bg-surface-800/40 p-3 space-y-2 flex-1 min-h-0">
                <div className="text-sm text-gray-200">
                  <span className="text-gray-500">Outcome </span>
                  <span className="font-semibold capitalize">{decisionExplain.decision}</span>
                  <span className="text-gray-500"> · Score </span>
                  <span className="font-mono tabular-nums">{decisionExplain.score.toFixed(1)}</span>
                  <span className="text-gray-500">/100</span>
                </div>
                {decisionExplain.inference_context &&
                (decisionExplain.inference_context.driver_explain?.length ?? 0) > 0 ? (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">Top drivers</div>
                    <ul className="text-sm text-gray-200 space-y-1">
                      {decisionExplain.inference_context.driver_explain!.slice(0, 3).map((d) => (
                        <li key={d.reason} className="flex flex-wrap gap-x-2 gap-y-0.5">
                          <span className="text-[10px] uppercase tracking-wide text-gray-500 px-1.5 py-0.5 rounded bg-surface-700">
                            {d.category}
                          </span>
                          <span>{d.label}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : decisionExplain.inference_context && decisionExplain.inference_context.driver_reasons.length > 0 ? (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">Top drivers</div>
                    <ul className="text-sm text-gray-300 list-disc list-inside space-y-0.5">
                      {decisionExplain.inference_context.driver_reasons.slice(0, 3).map((d) => (
                        <li key={d} className="text-xs">
                          {d}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {decisionExplain.inference_context?.ml_summary ? (
                  <p className="text-sm text-gray-300 leading-snug border-t border-surface-700 pt-2">
                    {decisionExplain.inference_context.ml_summary}
                  </p>
                ) : (
                  <p className="text-xs text-gray-500 italic">No ML narrative attached to this audit.</p>
                )}
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500">No decision audit available for this trace.</p>
          )}
        </div>

        {/* Decision controls */}
        <div className="xl:col-span-3 bg-surface-900 border border-surface-700 rounded-xl p-4 flex flex-col gap-4 min-h-[8rem]">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Decisions</h3>
          <div className="space-y-3 flex-1">
            <div>
              <label className="block text-xs text-gray-500 mb-1" htmlFor="case-status-select">
                Status
              </label>
              <select
                id="case-status-select"
                value={caseData.status}
                onChange={(e) => handleStatusChange(e.target.value)}
                disabled={statusUpdating}
                className="w-full bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                <option value="open">Open</option>
                <option value="investigating">Investigating</option>
                <option value="resolved">Resolved</option>
                <option value="closed">Closed</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1" htmlFor="case-priority-select">
                Priority
              </label>
              <select
                id="case-priority-select"
                value={caseData.priority}
                onChange={(e) => handlePriorityChange(e.target.value)}
                className="w-full bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
          </div>
          <div className="flex flex-col gap-2 mt-1">
            <Link
              to={`/investigation?case_id=${encodeURIComponent(caseData.id)}&tenant_id=${encodeURIComponent(caseData.tenant_id)}`}
              className="block text-center text-xs font-medium px-3 py-2.5 rounded-lg bg-brand-600/20 text-brand-300 hover:bg-brand-600/30 transition-colors border border-brand-500/30"
            >
              Open in Investigation Copilot
            </Link>
            <button
              type="button"
              disabled={!decisionExplain?.rule_hits?.length}
              title={
                decisionExplain?.rule_hits?.length
                  ? "Open the visual rule builder with the rule that fired on this audit"
                  : "No rule hits on this trace — tune is unavailable"
              }
              onClick={() => setTuneRuleOpen(true)}
              className="w-full text-center text-xs font-medium px-3 py-2.5 rounded-lg bg-surface-800 text-gray-200 hover:bg-surface-700 transition-colors border border-surface-600 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Tune rule
            </button>
          </div>
        </div>
      </section>

      {advancedDevView ? (
        <div className="flex flex-wrap gap-2 items-center rounded-lg border border-surface-700 bg-surface-900/60 px-3 py-2">
          <span className="text-xs text-gray-500 mr-1">Dev tools</span>
          <button
            type="button"
            disabled={bundleBusy}
            onClick={() => void handleDownloadEvidenceBundle()}
            className="text-xs font-medium px-3 py-1.5 rounded-lg bg-surface-700 text-gray-200 hover:bg-surface-600 transition-colors border border-surface-600 disabled:opacity-50"
          >
            {bundleBusy ? "Preparing bundle…" : "Download evidence bundle (JSON)"}
          </button>
          {caseData.trace_id ? (
            <Link
              to={`/investigation/dag-trace?trace_id=${encodeURIComponent(caseData.trace_id)}&tenant_id=${encodeURIComponent(caseData.tenant_id)}`}
              className="text-xs font-medium px-3 py-1.5 rounded-lg bg-surface-700 text-gray-200 hover:bg-surface-600 transition-colors border border-surface-600"
            >
              DAG execution trace
            </Link>
          ) : null}
        </div>
      ) : null}

      <SarManagementPanel caseId={caseData.id} tenantId={caseData.tenant_id} />

      <KycHandoverPanel caseId={caseData.id} tenantId={caseData.tenant_id} />

      {/* Info Panel */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <InfoCard label="Entity ID" value={caseData.entity_id} mono />
        <InfoCard label="Trace ID" value={caseData.trace_id ?? "—"} mono />
        <InfoCard label="Assigned Team" value={caseData.assigned_team || "Unassigned"} />
      </div>

      {advancedDevView ? (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-gray-300">Decision explainability (technical)</h3>
          </div>
          {decisionExplain ? (
            <>
              <div className="rounded-lg border border-surface-700/80 bg-surface-800/40 p-3 space-y-2">
                <div className="text-sm text-gray-200">
                  <span className="text-gray-500">Outcome </span>
                  <span className="font-semibold capitalize">{decisionExplain.decision}</span>
                  <span className="text-gray-500"> · Score </span>
                  <span className="font-mono tabular-nums">{decisionExplain.score.toFixed(1)}</span>
                  <span className="text-gray-500">/100</span>
                </div>
                <FraudScoreTrack score={decisionExplain.score} />
                {decisionExplain.inference_context ? (
                  <div className="space-y-1">
                    <p className="text-xs text-gray-400">
                      Confidence{" "}
                      <span className="text-gray-200 font-medium">
                        {decisionExplain.inference_context.confidence_tier}
                      </span>
                      {decisionExplain.inference_context.schema_version
                        ? ` · Schema v${decisionExplain.inference_context.schema_version}`
                        : ""}
                    </p>
                    {decisionExplain.inference_context.confidence_tier_label ? (
                      <p className="text-xs text-gray-300 leading-snug">{decisionExplain.inference_context.confidence_tier_label}</p>
                    ) : null}
                    <div className="text-xs text-gray-500">
                      Confidence sources:{" "}
                      <span className="text-gray-300">
                        calibration {decisionExplain.inference_context.calibration_profile}@v
                        {decisionExplain.inference_context.calibration_profile_version} · location{" "}
                        {(decisionExplain.inference_context.location_confidence * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="text-xs text-gray-500">
                      Source routing:{" "}
                      <span className="text-gray-300 font-mono">
                        cal={decisionExplain.inference_context.confidence_sources.calibration} ·
                        counter={decisionExplain.inference_context.confidence_sources.counter} ·
                        loc={decisionExplain.inference_context.confidence_sources.location}
                      </span>
                    </div>
                  </div>
                ) : null}
                {decisionExplain.inference_context &&
                (decisionExplain.inference_context.driver_explain?.length ?? 0) > 0 ? (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">Top drivers</div>
                    <ul className="text-sm text-gray-200 space-y-1">
                      {decisionExplain.inference_context.driver_explain!.slice(0, 4).map((d) => (
                        <li key={d.reason} className="flex flex-wrap gap-x-2 gap-y-0.5">
                          <span className="text-[10px] uppercase tracking-wide text-gray-500 px-1.5 py-0.5 rounded bg-surface-700">
                            {d.category}
                          </span>
                          <span>{d.label}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : decisionExplain.inference_context && decisionExplain.inference_context.driver_reasons.length > 0 ? (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">Top drivers</div>
                    <ul className="text-sm text-gray-200 list-disc list-inside space-y-0.5">
                      {decisionExplain.inference_context.driver_reasons.slice(0, 3).map((d) => (
                        <li key={d} className="font-mono text-xs">
                          {d}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {decisionExplain.inference_context?.ml_summary ? (
                  <p className="text-sm text-gray-300 leading-snug border-t border-surface-700 pt-2">
                    {decisionExplain.inference_context.ml_summary}
                  </p>
                ) : null}
                <p className="text-xs text-gray-500 leading-snug">
                  Review and block thresholds are defined in your org policy.
                </p>
              </div>

                <div className="space-y-3 border-t border-surface-700 pt-3">
                  {decisionExplain.inference_context ? (
                    <>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <InferenceMetricTrack
                          label="Integrity confidence"
                          value={decisionExplain.inference_context.integrity_confidence}
                          variant="trust"
                          hoverDetail={
                            <InferenceIntegrityHoverBody ctx={decisionExplain.inference_context} />
                          }
                        />
                        <InferenceMetricTrack
                          label="Tamper risk"
                          value={decisionExplain.inference_context.tamper_risk}
                          variant="risk"
                          hoverDetail={<InferenceTamperHoverBody ctx={decisionExplain.inference_context} />}
                        />
                        <InferenceMetricTrack
                          label="Replay risk"
                          value={decisionExplain.inference_context.replay_risk}
                          variant="risk"
                          hoverDetail={<InferenceReplayHoverBody ctx={decisionExplain.inference_context} />}
                        />
                        <InferenceMetricTrack
                          label="Network trust"
                          value={decisionExplain.inference_context.network_trust}
                          variant="trust"
                          hoverDetail={
                            <InferenceNetworkTrustHoverBody ctx={decisionExplain.inference_context} />
                          }
                        />
                        <InferenceMetricTrack
                          label="Geo consistency risk"
                          value={decisionExplain.inference_context.geo_consistency_risk}
                          variant="risk"
                          hoverDetail={
                            <InferenceGeoConsistencyHoverBody ctx={decisionExplain.inference_context} />
                          }
                        />
                        {decisionExplain.inference_context.colocation_risk > 0 && (
                          <InferenceMetricTrack
                            label="Colocation risk"
                            value={decisionExplain.inference_context.colocation_risk}
                            variant="risk"
                            hoverDetail={
                              <InferenceColocationHoverBody ctx={decisionExplain.inference_context} />
                            }
                          />
                        )}
                        {decisionExplain.inference_context.impossible_travel_risk > 0 && (
                          <InferenceMetricTrack
                            label="Impossible travel (proxy)"
                            value={decisionExplain.inference_context.impossible_travel_risk}
                            variant="risk"
                            hoverDetail={
                              <InferenceImpossibleTravelHoverBody ctx={decisionExplain.inference_context} />
                            }
                          />
                        )}
                      </div>
                      <div className="text-xs text-gray-500">
                        Velocity (5m / 1h / 24h):{" "}
                        <InfoHover
                          heading="Velocity ladder"
                          detail={<VelocityHoverBody ctx={decisionExplain.inference_context} />}
                          className="inline-flex"
                        >
                          <span className="text-gray-300 font-mono tabular-nums">
                            {decisionExplain.inference_context.velocity_events_5m} /{" "}
                            {decisionExplain.inference_context.velocity_events_1h} /{" "}
                            {decisionExplain.inference_context.velocity_events_24h}
                          </span>
                        </InfoHover>
                      </div>
                      {decisionExplain.inference_context.external_signal_score > 0 && (
                        <div className="text-xs text-gray-500">
                          External signal score:{" "}
                          <InfoHover
                            heading="External signal"
                            detail={<ExternalSignalHoverBody ctx={decisionExplain.inference_context} />}
                            className="inline-flex"
                          >
                            <span className="text-gray-300 font-mono tabular-nums">
                              {(decisionExplain.inference_context.external_signal_score * 100).toFixed(1)}%
                            </span>
                          </InfoHover>
                          {decisionExplain.inference_context.external_signal_providers.length > 0 && (
                            <>
                              {" · providers "}
                              <span className="text-gray-300">
                                {decisionExplain.inference_context.external_signal_providers.join(", ")}
                              </span>
                            </>
                          )}
                        </div>
                      )}
                      {decisionExplain.inference_context.policy_experiment_id && (
                        <div className="text-xs text-gray-500">
                          Policy experiment:{" "}
                          <span className="text-gray-300 font-mono">{decisionExplain.inference_context.policy_experiment_id}</span>
                        </div>
                      )}
                      {decisionExplain.inference_context.driver_reasons.length > 3 && (
                        <div>
                          <div className="text-xs font-medium text-gray-500 mb-1">All drivers</div>
                          <ul className="text-xs text-gray-300 list-disc list-inside space-y-0.5">
                            {decisionExplain.inference_context.driver_reasons.map((d) => (
                              <li key={d} className="font-mono">
                                {d}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {(decisionExplain.inference_context.ml_top_factors?.length ?? 0) > 0 && (
                        <div className="pt-2 border-t border-surface-700 space-y-1">
                          <div className="text-xs font-medium text-gray-500">ML factors</div>
                          {decisionExplain.inference_context.ml_model && (
                            <div className="text-xs text-gray-500 font-mono">
                              model: {decisionExplain.inference_context.ml_model}
                            </div>
                          )}
                          <ul className="text-xs text-gray-300 list-disc list-inside space-y-0.5">
                            {decisionExplain.inference_context.ml_top_factors!.map((f) => (
                              <li key={f.code}>
                                <span className="font-mono text-brand-300">{f.code}</span>
                                <span className="text-gray-500"> ({f.impact})</span> — {f.description}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </>
                  ) : null}
                  <div className="flex flex-wrap gap-2">
                    {decisionExplain.rule_hits.map((h) => (
                      <span key={h} className="px-2 py-0.5 bg-brand-500/20 text-brand-300 text-xs rounded-full">
                        {h}
                      </span>
                    ))}
                    {decisionExplain.rule_hits.length === 0 && (
                      <span className="text-xs text-gray-500">No rule hits</span>
                    )}
                  </div>
                  {decisionExplain.inference_context && decisionExplain.inference_context.top_signals.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {decisionExplain.inference_context.top_signals.map((s) => (
                        <span key={s} className="px-2 py-0.5 bg-surface-700 text-gray-300 text-xs rounded-full">
                          {s}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
            </>
          ) : (
            <span className="text-xs text-gray-500">No decision audit available</span>
          )}
          {decisionExplain?.evaluate_payload ? (
            <details className="rounded-lg border border-surface-700 bg-surface-950/40 p-3">
              <summary className="cursor-pointer text-xs font-medium text-gray-400 select-none">
                Raw audit envelope (evaluate_payload JSON)
              </summary>
              <pre className="mt-2 max-h-48 overflow-auto text-[11px] text-gray-400 font-mono whitespace-pre-wrap break-all">
                {JSON.stringify(decisionExplain.evaluate_payload, null, 2)}
              </pre>
            </details>
          ) : null}
        </div>
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-2">
          <h3 className="text-sm font-semibold text-gray-300">Graph Risk Context</h3>
          {graphRisk ? (
            <>
              <InferenceMetricTrack
                label="Graph risk score (0–1)"
                value={graphRisk.risk_score}
                variant="risk"
                hoverDetail={
                  <GraphMetricHoverBody
                    risk={graphRisk}
                    inference={decisionExplain?.inference_context ?? null}
                  />
                }
              />
              <div className="text-xs text-gray-400 pt-1">
                Community size:{" "}
                <InfoHover
                  heading="Community size"
                  detail={
                    <GraphMetricHoverBody
                      risk={graphRisk}
                      inference={decisionExplain?.inference_context ?? null}
                    />
                  }
                  className="inline-flex"
                >
                  <span className="text-gray-200 font-mono tabular-nums">{graphRisk.community_size}</span>
                </InfoHover>
              </div>
              <div className="flex flex-wrap gap-2">
                {graphRisk.risk_factors.map((f) => (
                  <span key={f} className="px-2 py-0.5 bg-surface-700 text-gray-300 text-xs rounded-full">{f}</span>
                ))}
              </div>
            </>
          ) : (
            <span className="text-xs text-gray-500">No graph risk data available</span>
          )}
        </div>
      </div>
      ) : null}

      {/* Labels */}
      <div className="bg-surface-900 border border-surface-700 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Labels</h3>
        <div className="flex flex-wrap gap-2 mb-3">
          {caseData.labels.map((l) => (
            <span
              key={l}
              className="px-2 py-0.5 bg-surface-700 text-gray-300 text-xs rounded-full"
            >
              {l}
            </span>
          ))}
          {caseData.labels.length === 0 && (
            <span className="text-xs text-gray-500">No labels</span>
          )}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="Add label..."
            value={labelInput}
            onChange={(e) => setLabelInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAddLabel()}
            className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-1.5 flex-1 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <button
            onClick={handleAddLabel}
            className="px-3 py-1.5 bg-surface-700 hover:bg-surface-600 text-gray-300 text-sm rounded-lg transition-colors"
          >
            Add
          </button>
        </div>
      </div>

      {/* Tabs — URL ?tab=timeline|audit|graph for sharing & multi-case workflow */}
      <div className="border-b border-surface-700" role="tablist" aria-label="Case views">
        <div className="flex gap-1 sm:gap-6 flex-wrap">
          {CASE_DETAIL_TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={activeTab === tab}
              id={`case-tab-${tab}`}
              onClick={() => setActiveTab(tab)}
              className={`pb-3 px-1 sm:px-0 text-sm font-medium capitalize transition-colors border-b-2 ${
                activeTab === tab
                  ? "text-brand-400 border-brand-400"
                  : "text-gray-400 border-transparent hover:text-gray-200"
              }`}
            >
              {tab === "graph" ? "Entity Graph" : tab}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === "timeline" && (
        <div
          role="tabpanel"
          id="case-panel-timeline"
          aria-labelledby="case-tab-timeline"
        >
          <TimelineTab
            comments={caseData.comments ?? []}
            commentText={commentText}
            onTextChange={setCommentText}
            onSubmit={handleAddComment}
            submitting={commentSubmitting}
          />
        </div>
      )}
      {activeTab === "audit" && (
        <div role="tabpanel" id="case-panel-audit" aria-labelledby="case-tab-audit">
          <AuditTab caseData={caseData} />
        </div>
      )}
      {activeTab === "graph" && (
        <div role="tabpanel" id="case-panel-graph" aria-labelledby="case-tab-graph">
          <GraphTab
            caseId={caseData.id}
            entityId={caseData.entity_id}
            tenantId={caseData.tenant_id}
            graphSnapshot={caseData.graph_snapshot ?? null}
            eventTimeIso={caseData.created_at}
            showRawDevTables={advancedDevView}
          />
        </div>
      )}

      <TuneRuleModal
        open={tuneRuleOpen}
        onClose={() => setTuneRuleOpen(false)}
        ruleHits={decisionExplain?.rule_hits ?? []}
      />
      </div>
      <KnowledgeGraphDesktopRail
        entityId={caseData.entity_id}
        tenantId={caseData.tenant_id}
        state={knowledgeGraphState}
      />
      <ShadowChatSidebar
        caseId={caseData.id}
        tenantId={caseData.tenant_id}
        caseTitle={caseData.title ?? undefined}
        open={shadowChatOpen}
        onOpenChange={setShadowChatOpen}
      />
    </div>
  );
}

function InfoCard({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-4">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div
        className={`text-sm text-gray-200 ${mono ? "font-mono" : ""} break-all`}
      >
        {value}
      </div>
    </div>
  );
}

function TimelineTab({
  comments,
  commentText,
  onTextChange,
  onSubmit,
  submitting,
}: {
  comments: NonNullable<Case["comments"]>;
  commentText: string;
  onTextChange: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  submitting: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="space-y-3 max-h-96 overflow-y-auto">
        {comments.map((c, i) => (
          <div
            key={i}
            className="bg-surface-800 border border-surface-700 rounded-lg p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-brand-400">
                {c.author}
              </span>
              <span className="text-xs text-gray-500">
                {new Date(c.timestamp).toLocaleString()}
              </span>
            </div>
            <p className="text-sm text-gray-300">{c.text}</p>
          </div>
        ))}
        {comments.length === 0 && (
          <p className="text-gray-500 text-sm text-center py-8">
            No comments yet
          </p>
        )}
      </div>
      <form onSubmit={onSubmit} className="flex gap-3">
        <input
          type="text"
          value={commentText}
          onChange={(e) => onTextChange(e.target.value)}
          placeholder="Add a comment..."
          className="flex-1 bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-4 py-2.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <button
          type="submit"
          disabled={submitting || !commentText.trim()}
          className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {submitting ? "..." : "Send"}
        </button>
      </form>
    </div>
  );
}

function AuditTab({ caseData }: { caseData: Case }) {
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-5">
      <h3 className="text-sm font-semibold text-gray-300 mb-3">Audit Trail</h3>
      <div className="space-y-3 text-sm">
        <AuditRow
          time={caseData.created_at}
          action="Case created"
          detail={`Priority: ${caseData.priority}`}
        />
        {caseData.assigned_team && (
          <AuditRow
            time={caseData.created_at}
            action="Assigned to team"
            detail={caseData.assigned_team}
          />
        )}
        {(caseData.comments ?? []).map((c, i) => (
          <AuditRow
            key={i}
            time={c.timestamp}
            action={`Comment by ${c.author}`}
            detail={c.text.slice(0, 80)}
          />
        ))}
        <AuditRow
          time={caseData.updated_at}
          action="Last updated"
          detail={`Status: ${caseData.status}`}
        />
      </div>
    </div>
  );
}

function AuditRow({
  time,
  action,
  detail,
}: {
  time: string;
  action: string;
  detail: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-2 h-2 rounded-full bg-surface-500 mt-1.5 flex-shrink-0" />
      <div className="flex-1">
        <div className="flex items-center justify-between">
          <span className="text-gray-200 font-medium">{action}</span>
          <span className="text-xs text-gray-500">
            {new Date(time).toLocaleString()}
          </span>
        </div>
        <p className="text-gray-400 text-xs mt-0.5">{detail}</p>
      </div>
    </div>
  );
}

const NODE_COLORS: Record<string, string> = {
  Person: "#3b82f6",
  Account: "#22c55e",
  Device: "#f97316",
  DeviceCluster: "#7c3aed",
  Payment: "#a855f7",
  Email: "#06b6d4",
  IP: "#ec4899",
};

const GRAPH_OPTIONS: Options = {
  nodes: {
    shape: "dot",
    size: 20,
    font: { color: "#e5e7eb", size: 12, face: "system-ui" },
    borderWidth: 2,
  },
  edges: {
    color: { color: "#3d4463", highlight: "#60a5fa" },
    font: { color: "#9ca3af", size: 10, face: "system-ui", align: "middle" },
    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
    smooth: { type: "continuous", enabled: true, roundness: 0.5 },
  },
  physics: {
    forceAtlas2Based: {
      gravitationalConstant: -30,
      centralGravity: 0.005,
      springLength: 150,
      springConstant: 0.08,
    },
    solver: "forceAtlas2Based",
    stabilization: { iterations: 100 },
  },
  interaction: {
    hover: true,
    zoomView: true,
    dragView: true,
  },
};

function GraphTab({
  caseId,
  entityId,
  tenantId,
  graphSnapshot,
  eventTimeIso,
  showRawDevTables = true,
}: {
  caseId: string;
  entityId: string;
  tenantId: string;
  graphSnapshot?: Record<string, unknown> | null;
  /** Case/trace time shown on the “At event” side of the slider. */
  eventTimeIso?: string | null;
  /** When false, hide the raw node/edge table (Advanced / Dev View). */
  showRawDevTables?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const [graphData, setGraphData] = useState<SubgraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  /** 0 = decision-time snapshot, 100 = live subgraph */
  const [timeTravel, setTimeTravel] = useState(100);
  /** Right-click Janus/local subgraph node annotations (browser-local per case). */
  const [nodeAnnotations, setNodeAnnotations] = useState<Record<string, string>>({});
  const [showAnnotationLayer, setShowAnnotationLayer] = useState(true);
  /** Collapse vertices that share ``device_hash`` (live vis-network + evidence snapshot). */
  const [entityClustering, setEntityClustering] = useState(true);
  const [annotationPopover, setAnnotationPopover] = useState<{
    clientX: number;
    clientY: number;
    nodeId: string;
  } | null>(null);

  const snapshotParsed = useMemo(() => {
    if (!graphSnapshot || typeof graphSnapshot !== "object") return null;
    return parseGraphSnapshot(graphSnapshot, { clusterByDeviceHash: entityClustering });
  }, [graphSnapshot, entityClustering]);

  const displayGraph = useMemo(() => {
    if (!graphData) return null;
    if (!entityClustering) return graphData;
    return clusterSubgraphByDeviceHash(graphData.nodes, graphData.edges);
  }, [graphData, entityClustering]);

  const hasSnapshot = (snapshotParsed?.nodes.length ?? 0) > 0;
  const showEventView = hasSnapshot && timeTravel < 50;

  useEffect(() => {
    if (showEventView) setSelectedNode(null);
  }, [showEventView]);

  useEffect(() => {
    setNodeAnnotations(loadGraphAnnotations(tenantId, caseId));
  }, [tenantId, caseId]);

  useEffect(() => {
    if (!selectedNode || !displayGraph) return;
    if (!displayGraph.nodes.some((n) => n.id === selectedNode)) {
      setSelectedNode(null);
    }
  }, [displayGraph, selectedNode]);

  useEffect(() => {
    (async () => {
      try {
        const data = await graph.subgraph(entityId, tenantId, 2);
        setGraphData(data);
      } catch (e) {
        setError(toUserFacingError(e, { subject: "Case graph", action: "load related entity graph" }));
      } finally {
        setLoading(false);
      }
    })();
  }, [entityId, tenantId]);

  useEffect(() => {
    if (!displayGraph || !containerRef.current || showEventView) return;
    if (displayGraph.nodes.length === 0) return;

    const nodes = new DataSet(
      displayGraph.nodes.map((n) => {
        const primaryLabel = n.labels?.[0] ?? "Node";
        const baseBg =
          NODE_COLORS[primaryLabel === DEVICE_CLUSTER_GRAPH_LABEL ? "DeviceCluster" : primaryLabel] ??
          "#6b7280";
        const note = nodeAnnotations[n.id];
        const ring = Boolean(showAnnotationLayer && note);
        const memberCount =
          typeof n.properties?.cluster_member_count === "number" ? n.properties.cluster_member_count : null;
        const shortLabel =
          primaryLabel === DEVICE_CLUSTER_GRAPH_LABEL && memberCount != null
            ? `${memberCount} · shared device`
            : n.id.length > 20
              ? n.id.slice(0, 20) + "\u2026"
              : n.id;
        const titleBase =
          primaryLabel === DEVICE_CLUSTER_GRAPH_LABEL &&
          typeof n.properties?.device_hash === "string" &&
          typeof n.properties?.cluster_member_ids === "string"
            ? `${primaryLabel}\ndevice_hash: ${n.properties.device_hash}\nmembers: ${n.properties.cluster_member_ids}`
            : `${primaryLabel}: ${n.id}`;
        const title = note ? `${titleBase}\n\nAnnotation:\n${note}` : titleBase;
        return {
          id: n.id,
          label: shortLabel,
          title,
          color: {
            background: baseBg,
            border: ring ? "#f59e0b" : baseBg,
            highlight: {
              background: "#60a5fa",
              border: "#3b82f6",
            },
          },
          borderWidth: ring ? 3 : 2,
        };
      }),
    );

    const edges = new DataSet(
      displayGraph.edges.map((e, i) => ({
        id: i,
        from: e.from_id,
        to: e.to_id,
        label: e.type,
      })),
    );

    const net = new Network(containerRef.current, { nodes, edges }, GRAPH_OPTIONS);
    networkRef.current = net;

    net.on("click", (params) => {
      if (params.nodes.length > 0) {
        setSelectedNode(params.nodes[0] as string);
      } else {
        setSelectedNode(null);
      }
    });

    net.on("oncontext", (params: { event?: MouseEvent; nodes?: string[] }) => {
      params.event?.preventDefault();
      const nid = params.nodes?.[0];
      const ev = params.event;
      if (!nid || !ev) return;
      setAnnotationPopover({ clientX: ev.clientX, clientY: ev.clientY, nodeId: nid });
      setSelectedNode(nid);
    });

    return () => {
      net.destroy();
      networkRef.current = null;
    };
  }, [displayGraph, showEventView, nodeAnnotations, showAnnotationLayer]);

  const selectedNodeData = displayGraph?.nodes.find((n) => n.id === selectedNode);

  const liveCounts = displayGraph
    ? { nodes: displayGraph.nodes.length, edges: displayGraph.edges.length }
    : null;

  const timeTravelChrome = hasSnapshot ? (
    <TimeTravelSlider
      value={timeTravel}
      onChange={setTimeTravel}
      eventTimeIso={eventTimeIso ?? undefined}
      snapshotNodeCount={snapshotParsed?.nodes.length ?? null}
      liveNodeCount={liveCounts?.nodes ?? null}
    />
  ) : (
    <p className="text-xs text-gray-500 border border-dashed border-surface-600 rounded-lg px-3 py-2 bg-surface-950/40 leading-snug">
      No evidence-locker <span className="font-mono text-gray-400">graph_snapshot</span> on this case — time travel
      needs a persisted topology. Only the live subgraph is shown.
    </p>
  );

  const eventCaption =
    eventTimeIso != null && eventTimeIso !== ""
      ? new Date(eventTimeIso).toLocaleString()
      : "decision time";

  const snapshotViewport =
    hasSnapshot && graphSnapshot ? (
      <div className="space-y-2" data-testid="case-graph-event-view">
        <p className="text-xs text-gray-500">
          Topology frozen in the evidence bundle at <span className="text-gray-400">{eventCaption}</span> (immutable
          React Flow snapshot).
        </p>
        <SnapshotGraph snapshot={graphSnapshot} height={420} clusterByDeviceHash={entityClustering} />
      </div>
    ) : null;

  if (loading) {
    return (
      <div className="space-y-4">
        {timeTravelChrome}
        {showEventView && snapshotViewport ? (
          snapshotViewport
        ) : (
          <div className="flex items-center justify-center py-20">
            <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          </div>
        )}
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        {timeTravelChrome}
        {showEventView && snapshotViewport ? (
          snapshotViewport
        ) : (
          <>
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400 text-sm space-y-1">
              <p>{error}</p>
              <SupportIdHint
                message={error}
                className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
                buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
              />
            </div>
            {graphData && showRawDevTables ? (
              <GraphDataTable nodes={graphData.nodes} edges={graphData.edges} />
            ) : null}
          </>
        )}
      </div>
    );
  }

  if (!graphData) {
    return (
      <div className="space-y-4">
        {timeTravelChrome}
        <p className="text-sm text-gray-500">No graph data loaded.</p>
      </div>
    );
  }

  const emptyGraph =
    displayGraph != null && displayGraph.nodes.length === 0 && displayGraph.edges.length === 0;

  return (
    <div className="space-y-4">
      {timeTravelChrome}
      {showEventView && snapshotViewport ? (
        snapshotViewport
      ) : (
        <>
          {emptyGraph ? (
            <p className="text-sm text-gray-500 border border-surface-700 rounded-lg px-4 py-3 bg-surface-900/60">
              No graph nodes returned for this entity.
              {showRawDevTables
                ? " Use the table below if the API returned partial data, or widen subgraph depth when supported."
                : " Enable Advanced / Dev View for the raw node and edge table."}
            </p>
          ) : null}
          <div className="flex flex-col gap-2">
            {!emptyGraph ? (
              <p className="text-xs text-gray-500">
                Live subgraph — click a node for <span className="text-gray-400">graph context</span>;{" "}
                <span className="text-amber-200/90">right-click</span> a node to add an annotation (Janus / neighborhood
                vertex).
              </p>
            ) : null}
            {!emptyGraph ? (
              <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <label className="flex items-center gap-2 text-gray-400 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={entityClustering}
                      onChange={(e) => setEntityClustering(e.target.checked)}
                      className="rounded border-surface-600"
                    />
                    Cluster by <span className="font-mono text-gray-500">device_hash</span> (botnets)
                  </label>
                  <label className="flex items-center gap-2 text-gray-400 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={showAnnotationLayer}
                      onChange={(e) => setShowAnnotationLayer(e.target.checked)}
                      className="rounded border-surface-600"
                    />
                    Show annotation layer (amber ring + tooltip)
                  </label>
                </div>
                <span className="text-gray-600">Annotations stored in this browser for this case.</span>
              </div>
            ) : null}
            {!emptyGraph ? (
              <div
                ref={containerRef}
                className="flex-1 bg-surface-900 border border-surface-700 rounded-xl min-h-[320px]"
                style={{ height: 420 }}
                aria-label="Entity relationship graph"
              />
            ) : null}
          </div>
          {Object.keys(nodeAnnotations).length > 0 ? (
            <details className="rounded-xl border border-amber-500/25 bg-amber-950/15 px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium text-amber-200/90 select-none">
                Annotation layer ({Object.keys(nodeAnnotations).length})
              </summary>
              <ul className="mt-2 space-y-2 max-h-40 overflow-y-auto text-xs">
                {Object.entries(nodeAnnotations).map(([nid, text]) => (
                  <li key={nid} className="border-b border-surface-800 pb-2 last:border-0">
                    <div className="font-mono text-[10px] text-gray-500 truncate" title={nid}>
                      {nid}
                    </div>
                    <div className="text-gray-300 whitespace-pre-wrap">{text}</div>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <GraphContextPanel
            open={Boolean(selectedNode)}
            onClose={() => setSelectedNode(null)}
            tenantId={tenantId}
            entityId={selectedNode}
            nodeHint={selectedNodeData ?? undefined}
          />
          {showRawDevTables ? (
            <details open className="rounded-xl border border-surface-700 bg-surface-900/40 p-4">
              <summary className="cursor-pointer text-sm font-medium text-gray-300">
                Table view (nodes &amp; edges)
              </summary>
              <div className="mt-3 pt-3 border-t border-surface-700">
                <GraphDataTable nodes={graphData.nodes} edges={graphData.edges} />
              </div>
            </details>
          ) : null}
          {annotationPopover ? (
            <GraphAnnotationPopover
              open
              clientX={annotationPopover.clientX}
              clientY={annotationPopover.clientY}
              nodeId={annotationPopover.nodeId}
              initialText={nodeAnnotations[annotationPopover.nodeId] ?? ""}
              onSave={(text) => {
                const next = setGraphNodeAnnotation(tenantId, caseId, annotationPopover.nodeId, text);
                setNodeAnnotations(next);
                setAnnotationPopover(null);
              }}
              onRemove={() => {
                const next = setGraphNodeAnnotation(tenantId, caseId, annotationPopover.nodeId, null);
                setNodeAnnotations(next);
                setAnnotationPopover(null);
              }}
              onClose={() => setAnnotationPopover(null)}
            />
          ) : null}
        </>
      )}
    </div>
  );
}

function GraphDataTable({
  nodes,
  edges,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
}) {
  return (
    <div className="space-y-4 text-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <caption className="text-xs text-gray-500 text-left mb-2">Nodes</caption>
          <thead>
            <tr className="text-gray-400 border-b border-surface-700">
              <th className="py-2 pr-4 font-medium">ID</th>
              <th className="py-2 pr-4 font-medium">Labels</th>
            </tr>
          </thead>
          <tbody>
            {nodes.length === 0 ? (
              <tr>
                <td colSpan={2} className="py-4 text-gray-500">
                  No nodes
                </td>
              </tr>
            ) : (
              nodes.map((n) => (
                <tr key={n.id} className="border-b border-surface-800">
                  <td className="py-2 pr-4 font-mono text-xs text-gray-200 align-top">{n.id}</td>
                  <td className="py-2 text-gray-400 text-xs">{n.labels?.join(", ") || "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <caption className="text-xs text-gray-500 text-left mb-2">Edges</caption>
          <thead>
            <tr className="text-gray-400 border-b border-surface-700">
              <th className="py-2 pr-4 font-medium">From</th>
              <th className="py-2 pr-4 font-medium">To</th>
              <th className="py-2 font-medium">Type</th>
            </tr>
          </thead>
          <tbody>
            {edges.length === 0 ? (
              <tr>
                <td colSpan={3} className="py-4 text-gray-500">
                  No edges
                </td>
              </tr>
            ) : (
              edges.map((e, i) => (
                <tr key={`${e.from_id}-${e.to_id}-${i}`} className="border-b border-surface-800">
                  <td className="py-2 pr-4 font-mono text-xs text-gray-200">{e.from_id}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-gray-200">{e.to_id}</td>
                  <td className="py-2 text-gray-400 text-xs">{e.type}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
