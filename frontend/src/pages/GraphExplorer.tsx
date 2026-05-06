import { useState, useRef, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import {
  graph,
  type SubgraphResponse,
  type CommunityResult,
  type FraudRingResult,
  type GraphNode,
} from "../api/client";
import { GraphContextPanel } from "../components/GraphContextPanel";
import RiskScore from "../components/RiskScore";
import { PageTitle } from "../components/PageTitle";
import { SupportIdHint } from "../components/SupportIdHint";
import { toUserFacingError } from "../utils/userFacingErrors";
import { Network, type Options } from "vis-network";
import { DataSet } from "vis-data";

const NODE_COLORS: Record<string, string> = {
  Person: "#3b82f6",
  Account: "#22c55e",
  Device: "#f97316",
  Payment: "#a855f7",
  Email: "#06b6d4",
  IP: "#ec4899",
  Address: "#84cc16",
};

const GRAPH_OPTIONS: Options = {
  nodes: {
    shape: "dot",
    size: 22,
    font: { color: "#e5e7eb", size: 12, face: "system-ui" },
    borderWidth: 2,
    shadow: { enabled: true, color: "rgba(0,0,0,0.3)", size: 6, x: 0, y: 2 },
  },
  edges: {
    color: { color: "#3d4463", highlight: "#60a5fa", hover: "#60a5fa" },
    font: { color: "#9ca3af", size: 10, face: "system-ui", align: "middle" },
    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
    smooth: { type: "continuous", enabled: true, roundness: 0.5 },
    width: 1.5,
  },
  physics: {
    forceAtlas2Based: {
      gravitationalConstant: -40,
      centralGravity: 0.005,
      springLength: 160,
      springConstant: 0.06,
      damping: 0.4,
    },
    solver: "forceAtlas2Based",
    stabilization: { iterations: 120 },
  },
  interaction: {
    hover: true,
    zoomView: true,
    dragView: true,
    tooltipDelay: 200,
  },
};

export default function GraphExplorer() {
  const [searchParams] = useSearchParams();
  const [entityId, setEntityId] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [graphData, setGraphData] = useState<SubgraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [riskScore, setRiskScore] = useState<number | null>(null);
  const [communities, setCommunities] = useState<CommunityResult[]>([]);
  const [fraudRings, setFraudRings] = useState<FraudRingResult[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [sidePanel, setSidePanel] = useState<"node" | "communities" | "rings" | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);

  const loadSubgraph = useCallback(async (eid: string, tid: string) => {
    const e = eid.trim();
    const t = tid.trim();
    if (!e || !t) return;
    setLoading(true);
    setError(null);
    setGraphData(null);
    setSelectedNode(null);
    setRiskScore(null);
    setCommunities([]);
    setFraudRings([]);
    setSidePanel(null);
    try {
      const data = await graph.subgraph(e, t, 2);
      setGraphData(data);
    } catch (err) {
      setError(toUserFacingError(err, { subject: "Entity graph", action: "load graph exploration data" }));
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSearch = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      await loadSubgraph(entityId, tenantId);
    },
    [entityId, tenantId, loadSubgraph],
  );

  useEffect(() => {
    const e = searchParams.get("entity_id")?.trim() ?? "";
    const t = searchParams.get("tenant_id")?.trim() ?? "";
    if (!e || !t) return;
    setEntityId(e);
    setTenantId(t);
    void loadSubgraph(e, t);
  }, [searchParams, loadSubgraph]);

  useEffect(() => {
    if (!graphData || !containerRef.current) return;

    const nodes = new DataSet(
      graphData.nodes.map((n) => {
        const nodeType = n.labels?.[0] ?? "Custom";
        return {
        id: n.id,
        label: n.id.length > 18 ? n.id.slice(0, 18) + "\u2026" : n.id,
        title: `${nodeType}: ${n.id}`,
        color: {
          background: NODE_COLORS[nodeType] ?? "#6b7280",
          border: NODE_COLORS[nodeType] ?? "#6b7280",
          highlight: { background: "#60a5fa", border: "#3b82f6" },
          hover: { background: NODE_COLORS[nodeType] ?? "#6b7280", border: "#60a5fa" },
        },
      }}),
    );

    const edges = new DataSet(
      graphData.edges.map((e, i) => ({
        id: i,
        from: e.from_id,
        to: e.to_id,
        label: e.type,
      })),
    );

    if (networkRef.current) {
      networkRef.current.destroy();
    }

    const net = new Network(containerRef.current, { nodes, edges }, GRAPH_OPTIONS);
    networkRef.current = net;

    net.on("click", (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0] as string;
        const node = graphData.nodes.find((n) => n.id === nodeId) ?? null;
        setSelectedNode(node);
        setSidePanel("node");
      }
    });

    return () => {
      net.destroy();
      networkRef.current = null;
    };
  }, [graphData]);

  const handleAnalyze = async () => {
    if (!entityId.trim() || !tenantId.trim()) return;
    setAnalyzing(true);
    try {
      const [rp, comm, rings] = await Promise.allSettled([
        graph.riskPropagation(entityId.trim(), tenantId.trim()),
        graph.communities(tenantId.trim()),
        graph.fraudRings(tenantId.trim()),
      ]);
      if (rp.status === "fulfilled") {
        const entities = rp.value.entities;
        if (entities.length > 0) {
          setRiskScore(entities[0].propagated_risk_score);
        }
      }
      if (comm.status === "fulfilled") {
        setCommunities(comm.value.communities);
      }
      if (rings.status === "fulfilled") {
        setFraudRings(rings.value.rings);
      }
    } catch {
      /* partial results ok */
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="p-6 h-full flex flex-col gap-5 animate-fade-in">
      <div className="flex items-center justify-between">
        <PageTitle module="graph">Graph Explorer</PageTitle>
      </div>
      <p className="text-xs text-amber-200/90 bg-amber-500/10 border border-amber-500/25 rounded-lg px-3 py-2">
        Super-node safety: production graphs should use server-side clustering / top-N expansion (see{" "}
        <code className="text-amber-100">graph-service/docs/DECISION_STREAM_INDEXER.md</code>) so shared ISP nodes do
        not overwhelm the browser.
      </p>

      {/* Search Bar */}
      <form onSubmit={handleSearch} className="flex flex-wrap gap-3">
        <input
          type="text"
          placeholder="Entity ID"
          value={entityId}
          onChange={(e) => setEntityId(e.target.value)}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-4 py-2.5 flex-1 min-w-[180px] focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <input
          type="text"
          placeholder="Tenant ID"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          className="bg-surface-800 border border-surface-600 text-gray-300 text-sm rounded-lg px-4 py-2.5 w-40 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-5 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {loading ? "Loading..." : "Search"}
        </button>
        {graphData && (
          <button
            type="button"
            onClick={handleAnalyze}
            disabled={analyzing}
            className="px-5 py-2.5 bg-amber-600/80 hover:bg-amber-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {analyzing ? "Analyzing..." : "Analyze"}
          </button>
        )}
      </form>

      {/* Node type legend */}
      <div className="flex flex-wrap gap-3">
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1.5 text-xs text-gray-400">
            <span
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: color }}
            />
            {type}
          </span>
        ))}
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm space-y-1">
          <p>{error}</p>
          <SupportIdHint
            message={error}
            className="flex flex-wrap items-center gap-2 text-[11px] text-red-300/85"
            buttonClassName="px-1.5 py-0.5 rounded border border-red-400/35 hover:border-red-300/50 hover:text-red-200 transition-colors"
          />
        </div>
      )}

      {/* Graph + Sidebar */}
      <div className="flex-1 flex gap-4 min-h-0">
        <div
          ref={containerRef}
          className="flex-1 bg-surface-900 border border-surface-700 rounded-xl relative"
          style={{ minHeight: 400 }}
        >
          {!graphData && !loading && (
            <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-sm">
              Enter an entity ID and tenant to explore the graph
            </div>
          )}
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
            </div>
          )}
        </div>

        {/* Side Panels */}
        {(sidePanel || riskScore !== null || communities.length > 0 || fraudRings.length > 0) && (
          <div className="w-72 flex-shrink-0 space-y-4 overflow-y-auto">
            {/* Risk Score */}
            {riskScore !== null && (
              <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 flex flex-col items-center">
                <h3 className="text-xs text-gray-500 font-medium mb-3">
                  Entity Risk Score
                </h3>
                <RiskScore score={riskScore} size={100} />
              </div>
            )}

            {/* Communities */}
            {communities.length > 0 && (
              <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-2">
                <h3 className="text-sm font-semibold text-gray-200">
                  Communities ({communities.length})
                </h3>
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {communities.map((c) => (
                    <div
                      key={c.community_id}
                      className="bg-surface-800 rounded-lg p-2.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-gray-400">
                          Community {c.community_id}
                        </span>
                        <span className="text-xs text-brand-400 font-medium">
                          {c.member_count} members
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {c.member_ids.slice(0, 5).map((m) => (
                          <span
                            key={m}
                            className="px-1.5 py-0.5 bg-surface-700 text-gray-400 text-[10px] rounded font-mono"
                          >
                            {m.length > 12 ? m.slice(0, 12) + "\u2026" : m}
                          </span>
                        ))}
                        {c.member_ids.length > 5 && (
                          <span className="text-[10px] text-gray-500">
                            +{c.member_ids.length - 5} more
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Fraud Rings */}
            {fraudRings.length > 0 && (
              <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-2">
                <h3 className="text-sm font-semibold text-red-400">
                  Fraud Rings ({fraudRings.length})
                </h3>
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {fraudRings.map((r, i) => (
                    <div
                      key={i}
                      className="bg-surface-800 border border-red-500/20 rounded-lg p-2.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-gray-400 font-mono">
                          Ring ({r.ring_size} members)
                        </span>
                        <span className="text-xs font-bold text-red-400">
                          {r.aggregate_tags.join(", ")}
                        </span>
                      </div>
                      <p className="text-xs text-gray-400 mt-1">{r.relationships.join(", ")}</p>
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {r.ring_members.slice(0, 4).map((m) => (
                          <span
                            key={m}
                            className="px-1.5 py-0.5 bg-red-500/10 text-red-300 text-[10px] rounded font-mono"
                          >
                            {m.length > 12 ? m.slice(0, 12) + "\u2026" : m}
                          </span>
                        ))}
                        {r.ring_members.length > 4 && (
                          <span className="text-[10px] text-gray-500">
                            +{r.ring_members.length - 4} more
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <GraphContextPanel
        open={sidePanel === "node" && Boolean(selectedNode)}
        onClose={() => {
          setSidePanel(null);
          setSelectedNode(null);
        }}
        tenantId={tenantId.trim()}
        entityId={selectedNode?.id ?? null}
        nodeHint={selectedNode ?? undefined}
      />
    </div>
  );
}
