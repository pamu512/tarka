import { useEffect, useState, useRef, useCallback } from "react";
import { Link, useParams, useNavigate, useSearchParams } from "react-router-dom";
import {
  cases,
  decisions,
  graph,
  type Case,
  type EntityRiskResult,
  type InferenceContext,
  normalizeInferenceContext,
  type SubgraphResponse,
} from "../api/client";
import StatusBadge from "../components/StatusBadge";
import PriorityBadge from "../components/PriorityBadge";
import { PageTitle } from "../components/PageTitle";
import { FraudScoreTrack } from "../components/FraudScoreTrack";
import { InferenceMetricTrack } from "../components/InferenceMetricTrack";
import { Network, type Options } from "vis-network";
import { DataSet } from "vis-data";

type Tab = "timeline" | "audit" | "graph";
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
  const [searchParams] = useSearchParams();
  const tenantIdFromUrl = searchParams.get("tenant_id") ?? "demo";
  const navigate = useNavigate();
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("timeline");
  const [commentText, setCommentText] = useState("");
  const [commentSubmitting, setCommentSubmitting] = useState(false);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [labelInput, setLabelInput] = useState("");
  const [decisionExplain, setDecisionExplain] = useState<DecisionExplain | null>(null);
  const [graphRisk, setGraphRisk] = useState<EntityRiskResult | null>(null);

  const fetchCase = useCallback(async () => {
    if (!caseId) return;
    try {
      const data = await cases.get(caseId, tenantIdFromUrl);
      setCaseData(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load case");
    } finally {
      setLoading(false);
    }
  }, [caseId, tenantIdFromUrl]);

  useEffect(() => {
    fetchCase();
  }, [fetchCase]);

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
      setError(e instanceof Error ? e.message : "Failed to update status");
    } finally {
      setStatusUpdating(false);
    }
  };

  const handlePriorityChange = async (newPriority: string) => {
    if (!caseId || !caseData) return;
    try {
      const updated = await cases.update(caseId, caseData.tenant_id, { priority: newPriority as Case["priority"] });
      setCaseData(updated);
    } catch {
      /* silent */
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
      setError(err instanceof Error ? err.message : "Failed to add comment");
    } finally {
      setCommentSubmitting(false);
    }
  };

  const handleAddLabel = async () => {
    if (!caseId || !caseData || !labelInput.trim()) return;
    try {
      await cases.addLabels(caseId, caseData.tenant_id, [labelInput.trim()]);
      await fetchCase();
      setLabelInput("");
    } catch {
      /* silent */
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

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {/* Back + Header */}
      <button
        onClick={() => navigate("/cases")}
        className="text-sm text-gray-400 hover:text-gray-200 transition-colors"
      >
        &larr; Back to Cases
      </button>

      <div className="flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
        <div className="space-y-1 min-w-0">
          <PageTitle module="cases">{caseData.title}</PageTitle>
          <p className="text-sm text-gray-400 font-mono">{caseData.id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            to={`/investigation?case_id=${encodeURIComponent(caseData.id)}&tenant_id=${encodeURIComponent(caseData.tenant_id)}`}
            className="text-xs font-medium px-3 py-1.5 rounded-lg bg-brand-600/20 text-brand-300 hover:bg-brand-600/30 transition-colors border border-brand-500/30"
          >
            Open in Investigation Copilot
          </Link>
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

      {/* Explainability */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-2">
          <h3 className="text-sm font-semibold text-gray-300">Decision Explainability</h3>
          {decisionExplain ? (
            <>
              <div className="text-xs text-gray-400">Decision: <span className="text-gray-200">{decisionExplain.decision}</span></div>
              <div className="space-y-1.5 pt-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs text-gray-400">Fraud score (0–100)</span>
                  <span className="text-sm font-mono text-gray-100 tabular-nums">{decisionExplain.score.toFixed(1)}</span>
                </div>
                <FraudScoreTrack score={decisionExplain.score} />
                <p className="text-[10px] text-gray-600 leading-snug">
                  Band copy is indicative; your org sets review and block thresholds in policy.
                </p>
              </div>
              {decisionExplain.recommended_action && (
                <div className="text-xs text-amber-400/90">
                  Recommended action: <span className="font-mono text-gray-200">{decisionExplain.recommended_action}</span>
                </div>
              )}
              {decisionExplain.inference_context ? (
                <>
                  <div className="text-xs text-gray-500 flex flex-wrap gap-x-3 gap-y-1 pt-1">
                    <span>
                      Tier:{" "}
                      <span className="text-gray-300">{decisionExplain.inference_context.confidence_tier}</span>
                    </span>
                    <span>schema v{decisionExplain.inference_context.schema_version}</span>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2 pt-2">
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
                  {decisionExplain.inference_context.driver_reasons.length > 0 && (
                    <div className="pt-1">
                      <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Top drivers</div>
                      <ul className="text-xs text-gray-400 list-disc list-inside space-y-0.5">
                        {decisionExplain.inference_context.driver_reasons.map((d) => (
                          <li key={d} className="font-mono text-[11px] text-gray-300">
                            {d}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {decisionExplain.rule_hits.map((h) => (
                  <span key={h} className="px-2 py-0.5 bg-brand-500/20 text-brand-300 text-xs rounded-full">{h}</span>
                ))}
                {decisionExplain.rule_hits.length === 0 && <span className="text-xs text-gray-500">No rule hits</span>}
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

      {/* Tabs */}
      <div className="border-b border-surface-700">
        <div className="flex gap-6">
          {(["timeline", "audit", "graph"] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`pb-3 text-sm font-medium capitalize transition-colors border-b-2 ${
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
        <TimelineTab
          comments={caseData.comments ?? []}
          commentText={commentText}
          onTextChange={setCommentText}
          onSubmit={handleAddComment}
          submitting={commentSubmitting}
        />
      )}
      {activeTab === "audit" && <AuditTab caseData={caseData} />}
      {activeTab === "graph" && (
        <GraphTab entityId={caseData.entity_id} tenantId={caseData.tenant_id} />
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
}: {
  entityId: string;
  tenantId: string;
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
        setError(e instanceof Error ? e.message : "Graph load failed");
      } finally {
        setLoading(false);
      }
    })();
  }, [entityId, tenantId]);

  useEffect(() => {
    if (!graphData || !containerRef.current) return;

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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400 text-sm">
        {error}
      </div>
    );
  }

  return (
    <div className="flex gap-4">
      <div
        ref={containerRef}
        className="flex-1 bg-surface-900 border border-surface-700 rounded-xl"
        style={{ height: 420 }}
      />
      {selectedNodeData && (
        <div className="w-64 bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-3">
          <h3 className="text-sm font-semibold text-gray-200">Node Details</h3>
          <div>
            <span className="text-xs text-gray-500">ID</span>
            <p className="text-sm text-gray-200 font-mono break-all">
              {selectedNodeData.id}
            </p>
          </div>
          <div>
            <span className="text-xs text-gray-500">Type</span>
            <p className="text-sm text-gray-200">{selectedNodeData.labels?.join(", ") || "Unknown"}</p>
          </div>
          {Object.entries(selectedNodeData.properties).map(([k, v]) => (
            <div key={k}>
              <span className="text-xs text-gray-500">{k}</span>
              <p className="text-sm text-gray-300 break-all">
                {String(v)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
