import { useEffect, useState, useRef, useCallback, useMemo } from "react";
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
import { SnapshotGraph } from "../components/CaseView/SnapshotGraph";
import { GraphContextPanel } from "../components/GraphContextPanel";
import { FraudScoreTrack } from "../components/FraudScoreTrack";
import { InferenceMetricTrack } from "../components/InferenceMetricTrack";
import { SarManagementPanel } from "../components/SarManagementPanel";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";
import { Network, type Options } from "vis-network";
import { DataSet } from "vis-data";

const CASE_DETAIL_TABS = ["timeline", "audit", "graph"] as const;
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

type DecisionExplain = {
  score: number;
  decision: string;
  reasons: string[];
  tags: string[];
  rule_hits: string[];
  recommended_action?: string | null;
  inference_context: InferenceContext | null;
};

export default function CaseDetail() {
  const { caseId } = useParams<{ caseId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { tenantId: workspaceTenantId } = useTenantEnvironment();
  const tenantEffective = (searchParams.get("tenant_id")?.trim() || workspaceTenantId || "demo").trim();
  const navigate = useNavigate();
  const { pinCase } = useAnalystWorkspace();
  const { toast } = useToast();
  const [showTechnicalDecision, setShowTechnicalDecision] = useState(false);
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

  useEffect(() => {
    if (!caseData) return;
    (async () => {
      try {
        if (caseData.trace_id) {
          const audit = await decisions.getAudit(caseData.trace_id, caseData.tenant_id);
          setDecisionExplain({
            score: audit.score,
            decision: audit.decision,
            reasons: [],
            tags: audit.tags || [],
            rule_hits: audit.rule_hits || [],
            recommended_action: audit.recommended_action ?? null,
            inference_context: normalizeInferenceContext(audit.inference_context),
          });
        } else {
          setDecisionExplain(null);
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
    })();
  }, [caseData]);

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

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <nav className="text-sm text-gray-500 flex flex-wrap items-center gap-2" aria-label="Breadcrumb">
        <Link to={casesListHref} className="text-brand-400 hover:text-brand-300">
          Cases
        </Link>
        <span aria-hidden>/</span>
        <span className="text-gray-300 truncate min-w-0 max-w-[min(100%,32rem)]">{caseData.title}</span>
      </nav>

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

      {decisionExplain?.recommended_action ? (
        <div className="sticky top-0 z-10 rounded-xl border border-amber-500/40 bg-amber-500/[0.12] backdrop-blur-sm px-4 py-3 shadow-lg shadow-black/20">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-200/90">
            Recommended next step
          </div>
          <p className="text-lg sm:text-xl font-semibold text-gray-50 mt-1 leading-snug">
            {humanizeRecommendedAction(decisionExplain.recommended_action)}
          </p>
          <details className="mt-2 text-sm">
            <summary className="cursor-pointer text-amber-200/80 hover:text-amber-100 select-none">
              Policy code
            </summary>
            <code className="mt-1 block text-xs text-gray-400 font-mono bg-surface-950/50 rounded px-2 py-1">
              {decisionExplain.recommended_action}
            </code>
          </details>
        </div>
      ) : null}

      <div className="flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
        <div className="space-y-1 min-w-0">
          <PageTitle module="cases">{caseData.title}</PageTitle>
          <p className="text-sm text-gray-400 font-mono">{caseData.id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={bundleBusy}
            onClick={() => void handleDownloadEvidenceBundle()}
            className="text-xs font-medium px-3 py-1.5 rounded-lg bg-surface-700 text-gray-200 hover:bg-surface-600 transition-colors border border-surface-600 disabled:opacity-50"
          >
            {bundleBusy ? "Preparing bundle…" : "Download evidence bundle (JSON)"}
          </button>
          <Link
            to={`/investigation?case_id=${encodeURIComponent(caseData.id)}&tenant_id=${encodeURIComponent(caseData.tenant_id)}`}
            className="text-xs font-medium px-3 py-1.5 rounded-lg bg-brand-600/20 text-brand-300 hover:bg-brand-600/30 transition-colors border border-brand-500/30"
          >
            Open in Investigation Copilot
          </Link>
          {caseData.trace_id ? (
            <Link
              to={`/investigation/dag-trace?trace_id=${encodeURIComponent(caseData.trace_id)}&tenant_id=${encodeURIComponent(caseData.tenant_id)}`}
              className="text-xs font-medium px-3 py-1.5 rounded-lg bg-surface-700 text-gray-200 hover:bg-surface-600 transition-colors border border-surface-600"
            >
              DAG execution trace
            </Link>
          ) : null}
          <StatusBadge status={caseData.status} />
          <PriorityBadge priority={caseData.priority} />
          <span
            className={`text-xs font-medium px-2 py-1 rounded-full ${
              slaPassed
                ? "bg-red-500/20 text-red-400"
                : "bg-green-500/20 text-green-400"
            }`}
          >
            SLA: {slaPassed ? "Breached" : "On Track"}
          </span>
        </div>
      </div>

      {/* Info Panel */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <InfoCard label="Entity ID" value={caseData.entity_id} mono />
        <InfoCard label="Trace ID" value={caseData.trace_id ?? "—"} mono />
        <InfoCard label="Assigned Team" value={caseData.assigned_team || "Unassigned"} />
      </div>

      <SarManagementPanel caseId={caseData.id} tenantId={caseData.tenant_id} />

      {/* Explainability — summary first; full metrics behind toggle */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-gray-300">Decision explainability</h3>
            {decisionExplain ? (
              <button
                type="button"
                aria-expanded={showTechnicalDecision}
                onClick={() => setShowTechnicalDecision((v) => !v)}
                className="text-xs font-medium text-brand-400 hover:text-brand-300"
              >
                {showTechnicalDecision ? "Hide technical detail" : "Show technical detail"}
              </button>
            ) : null}
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
                  Review and block thresholds are defined in your org policy. Expand technical detail for every signal.
                </p>
              </div>

              {showTechnicalDecision ? (
                <div className="space-y-3 border-t border-surface-700 pt-3">
                  {decisionExplain.inference_context ? (
                    <>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <InferenceMetricTrack
                          label="Integrity confidence"
                          value={decisionExplain.inference_context.integrity_confidence}
                          variant="trust"
                        />
                        <InferenceMetricTrack
                          label="Tamper risk"
                          value={decisionExplain.inference_context.tamper_risk}
                          variant="risk"
                        />
                        <InferenceMetricTrack
                          label="Replay risk"
                          value={decisionExplain.inference_context.replay_risk}
                          variant="risk"
                        />
                        <InferenceMetricTrack
                          label="Network trust"
                          value={decisionExplain.inference_context.network_trust}
                          variant="trust"
                        />
                        <InferenceMetricTrack
                          label="Geo consistency risk"
                          value={decisionExplain.inference_context.geo_consistency_risk}
                          variant="risk"
                        />
                        {decisionExplain.inference_context.colocation_risk > 0 && (
                          <InferenceMetricTrack
                            label="Colocation risk"
                            value={decisionExplain.inference_context.colocation_risk}
                            variant="risk"
                          />
                        )}
                        {decisionExplain.inference_context.impossible_travel_risk > 0 && (
                          <InferenceMetricTrack
                            label="Impossible travel (proxy)"
                            value={decisionExplain.inference_context.impossible_travel_risk}
                            variant="risk"
                          />
                        )}
                      </div>
                      <div className="text-xs text-gray-500">
                        Velocity (5m / 1h / 24h):{" "}
                        <span className="text-gray-300 font-mono tabular-nums">
                          {decisionExplain.inference_context.velocity_events_5m} /{" "}
                          {decisionExplain.inference_context.velocity_events_1h} /{" "}
                          {decisionExplain.inference_context.velocity_events_24h}
                        </span>
                      </div>
                      {decisionExplain.inference_context.external_signal_score > 0 && (
                        <div className="text-xs text-gray-500">
                          External signal score:{" "}
                          <span className="text-gray-300 font-mono tabular-nums">
                            {(decisionExplain.inference_context.external_signal_score * 100).toFixed(1)}%
                          </span>
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
              ) : null}
            </>
          ) : (
            <span className="text-xs text-gray-500">No decision audit available</span>
          )}
        </div>
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-2">
          <h3 className="text-sm font-semibold text-gray-300">Graph Risk Context</h3>
          {graphRisk ? (
            <>
              <InferenceMetricTrack
                label="Graph risk score (0–1)"
                value={graphRisk.risk_score}
                variant="risk"
              />
              <div className="text-xs text-gray-400 pt-1">
                Community size: <span className="text-gray-200 font-mono tabular-nums">{graphRisk.community_size}</span>
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

      {/* Actions */}
      <div className="flex flex-wrap gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">
            Change Status
          </label>
          <select
            value={caseData.status}
            onChange={(e) => handleStatusChange(e.target.value)}
            disabled={statusUpdating}
            className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            <option value="open">Open</option>
            <option value="investigating">Investigating</option>
            <option value="resolved">Resolved</option>
            <option value="closed">Closed</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">
            Change Priority
          </label>
          <select
            value={caseData.priority}
            onChange={(e) => handlePriorityChange(e.target.value)}
            className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
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
            entityId={caseData.entity_id}
            tenantId={caseData.tenant_id}
            graphSnapshot={caseData.graph_snapshot ?? null}
          />
        </div>
      )}
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
  entityId,
  tenantId,
  graphSnapshot,
}: {
  entityId: string;
  tenantId: string;
  graphSnapshot?: Record<string, unknown> | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const [graphData, setGraphData] = useState<SubgraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

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
    if (!graphData || !containerRef.current) return;
    if (graphData.nodes.length === 0) return;

    const nodes = new DataSet(
      graphData.nodes.map((n) => ({
        id: n.id,
        label: n.id.length > 20 ? n.id.slice(0, 20) + "\u2026" : n.id,
        title: `${n.labels?.[0] ?? "Node"}: ${n.id}`,
        color: {
          background: NODE_COLORS[n.labels?.[0] ?? ""] ?? "#6b7280",
          border: NODE_COLORS[n.labels?.[0] ?? ""] ?? "#6b7280",
          highlight: {
            background: "#60a5fa",
            border: "#3b82f6",
          },
        },
      })),
    );

    const edges = new DataSet(
      graphData.edges.map((e, i) => ({
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

    return () => {
      net.destroy();
      networkRef.current = null;
    };
  }, [graphData]);

  const selectedNodeData = graphData?.nodes.find((n) => n.id === selectedNode);

  const snapshotPanel =
    graphSnapshot != null && typeof graphSnapshot === "object" ? (
      <div className="space-y-2" data-testid="case-graph-snapshot-panel">
        <h3 className="text-sm font-semibold text-gray-300">Saved graph snapshot</h3>
        <p className="text-xs text-gray-500">
          Immutable evidence-locker topology (React Flow). Live entity graph from the API follows below.
        </p>
        <SnapshotGraph snapshot={graphSnapshot} height={300} />
      </div>
    ) : null;

  if (loading) {
    return (
      <div className="space-y-6">
        {snapshotPanel}
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        {snapshotPanel}
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400 text-sm space-y-1">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
        </div>
        {graphData ? <GraphDataTable nodes={graphData.nodes} edges={graphData.edges} /> : null}
      </div>
    );
  }

  if (!graphData) {
    return <p className="text-sm text-gray-500">No graph data loaded.</p>;
  }

  const emptyGraph = graphData.nodes.length === 0 && graphData.edges.length === 0;

  return (
    <div className="space-y-4">
      {snapshotPanel}
      {emptyGraph ? (
        <p className="text-sm text-gray-500 border border-surface-700 rounded-lg px-4 py-3 bg-surface-900/60">
          No graph nodes returned for this entity. Use the table below if the API returned partial data, or widen subgraph
          depth when supported.
        </p>
      ) : null}
      <div className="flex flex-col gap-2">
        {!emptyGraph ? (
          <p className="text-xs text-gray-500">
            Click a node to open the <span className="text-gray-400">graph context</span> panel (transactions, IPs,
            risk snapshot).
          </p>
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
      <GraphContextPanel
        open={Boolean(selectedNode)}
        onClose={() => setSelectedNode(null)}
        tenantId={tenantId}
        entityId={selectedNode}
        nodeHint={selectedNodeData ?? undefined}
      />
      <details open className="rounded-xl border border-surface-700 bg-surface-900/40 p-4">
        <summary className="cursor-pointer text-sm font-medium text-gray-300">
          Table view (nodes &amp; edges)
        </summary>
        <div className="mt-3 pt-3 border-t border-surface-700">
          <GraphDataTable nodes={graphData.nodes} edges={graphData.edges} />
        </div>
      </details>
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
