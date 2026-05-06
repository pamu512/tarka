import { type FormEvent, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { graph } from "../api/client";
import { GraphContextPanel } from "../components/GraphContextPanel";
import { LinkAnalysisForceGraph } from "../components/LinkAnalysisForceGraph";
import { PageTitle } from "../components/PageTitle";
import {
  type LinkAnalysisGraphNode,
  attachDisplayRiskToNodes,
  buildRiskScoreByEntityId,
  LINK_ANALYSIS_MAX_NODES,
  toForceGraphLinks,
} from "../domain/linkAnalysisGraph";
import { pruneSubgraphAsync } from "../domain/linkAnalysisPruneWorkerRunner";
import { toUserFacingError } from "../utils/userFacingErrors";

function defaultTenantId(): string {
  try {
    const t = localStorage.getItem("tarka.tenant_id");
    if (t && t.trim()) return t.trim();
  } catch {
    /* ignore */
  }
  return "demo";
}

export default function LinkAnalysisPage() {
  const [params, setParams] = useSearchParams();
  const entityId = (params.get("entity_id") || "").trim();
  const tenantId = (params.get("tenant_id") || "").trim() || defaultTenantId();
  const depthRaw = (params.get("depth") || "2").trim();
  const depth = Math.min(5, Math.max(1, Number.parseInt(depthRaw, 10) || 2));

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pruneNote, setPruneNote] = useState("");
  const [ctxOpen, setCtxOpen] = useState(false);
  const [ctxEntityId, setCtxEntityId] = useState<string | null>(null);
  const [ctxNodeHint, setCtxNodeHint] = useState<LinkAnalysisGraphNode | null>(null);
  const [graphPayload, setGraphPayload] = useState<{
    nodes: ReturnType<typeof attachDisplayRiskToNodes>;
    links: ReturnType<typeof toForceGraphLinks>;
  } | null>(null);

  const canLoad = entityId.length > 0 && tenantId.length > 0;

  useEffect(() => {
    if (!canLoad) {
      setGraphPayload(null);
      setPruneNote("");
      setError("");
    }
  }, [canLoad]);

  const load = useCallback(async () => {
    if (!canLoad) return;
    setLoading(true);
    setError("");
    setPruneNote("");
    setGraphPayload(null);
    setCtxOpen(false);
    setCtxEntityId(null);
    setCtxNodeHint(null);
    try {
      const [sub, riskProp, riskAnchor] = await Promise.all([
        graph.subgraph(entityId, tenantId, depth),
        graph.riskPropagation(entityId, tenantId, depth).catch(() => ({ entities: [] })),
        graph.entityRisk(entityId, tenantId).catch(() => null),
      ]);

      const pruned = await pruneSubgraphAsync(sub.nodes, sub.edges, entityId, LINK_ANALYSIS_MAX_NODES);
      if (pruned.originalNodeCount > pruned.prunedNodeCount) {
        setPruneNote(
          `Performance cap: subgraph had ${pruned.originalNodeCount.toLocaleString()} entities; ` +
            `showing ${pruned.prunedNodeCount.toLocaleString()} (seed + highest-degree neighbors).` +
            (sub.nodes.length > LINK_ANALYSIS_MAX_NODES
              ? " Pruning ran in a background worker so the main thread stayed responsive."
              : ""),
        );
      }

      const analyticsMap = buildRiskScoreByEntityId(riskAnchor, riskProp.entities ?? []);
      const nodes = attachDisplayRiskToNodes(pruned.nodes, analyticsMap);
      const links = toForceGraphLinks(pruned.edges);
      setGraphPayload({ nodes, links });
    } catch (e) {
      setError(toUserFacingError(e, { subject: "Link analysis", action: "load graph subgraph and risk analytics" }));
    } finally {
      setLoading(false);
    }
  }, [canLoad, depth, entityId, tenantId]);

  useEffect(() => {
    if (canLoad) void load();
  }, [canLoad, load]);

  const onSubmit = useCallback(
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const next = new URLSearchParams();
      next.set("entity_id", String(fd.get("entity_id") ?? "").trim());
      next.set("tenant_id", String(fd.get("tenant_id") ?? "").trim() || defaultTenantId());
      next.set("depth", String(fd.get("depth") ?? "2").trim() || "2");
      setParams(next);
    },
    [setParams],
  );

  const largeGraph = (graphPayload?.nodes.length ?? 0) > 800;

  return (
    <div className="p-6 space-y-4 max-w-[1400px] mx-auto">
      <PageTitle module="graph">JanusGraph link analysis (2D)</PageTitle>
      <p className="text-sm text-gray-400 max-w-3xl">
        Live subgraph from the graph service, overlaid with entity-risk and propagation scores. Pan and zoom on the
        canvas; risk is drawn on each node (amber monospace). Graphs over {LINK_ANALYSIS_MAX_NODES.toLocaleString()}{" "}
        entities are pruned or processed in a web worker so the tab stays responsive.
      </p>

      <form key={`${entityId}:${tenantId}:${depth}`} onSubmit={onSubmit} className="flex flex-wrap gap-3 items-end">
        <label className="text-xs text-gray-500 flex flex-col gap-1">
          Entity ID
          <input
            name="entity_id"
            defaultValue={entityId}
            className="bg-surface-900 border border-surface-700 rounded px-2 py-1.5 text-sm text-gray-200 w-56"
            placeholder="e.g. fraud_frank"
            required
          />
        </label>
        <label className="text-xs text-gray-500 flex flex-col gap-1">
          Tenant
          <input
            name="tenant_id"
            defaultValue={tenantId}
            className="bg-surface-900 border border-surface-700 rounded px-2 py-1.5 text-sm text-gray-200 w-40"
            placeholder="demo"
          />
        </label>
        <label className="text-xs text-gray-500 flex flex-col gap-1">
          Depth (1–5)
          <input
            name="depth"
            type="number"
            min={1}
            max={5}
            defaultValue={depth}
            className="bg-surface-900 border border-surface-700 rounded px-2 py-1.5 text-sm text-gray-200 w-24"
          />
        </label>
        <button
          type="submit"
          className="text-sm font-medium px-4 py-2 rounded-lg bg-brand-600 text-white hover:bg-brand-500 border border-brand-500/40"
        >
          Load subgraph
        </button>
      </form>

      {loading ? <p className="text-sm text-gray-500">Loading subgraph and risk overlays…</p> : null}
      {error ? (
        <p className="text-sm text-rose-300 border border-rose-500/30 rounded-md px-3 py-2 bg-rose-500/10">{error}</p>
      ) : null}
      {pruneNote ? (
        <p className="text-xs text-amber-200/90 border border-amber-500/30 rounded-md px-3 py-2 bg-amber-500/10">
          {pruneNote}
        </p>
      ) : null}

      {!canLoad && !loading ? (
        <p className="text-sm text-gray-500">Enter an entity ID and tenant to load JanusGraph neighborhood data.</p>
      ) : null}

      {graphPayload && graphPayload.nodes.length > 0 ? (
        <LinkAnalysisForceGraph
          graphData={graphPayload}
          largeGraph={largeGraph}
          onNodeClick={(id, node) => {
            setCtxEntityId(id);
            setCtxNodeHint(node);
            setCtxOpen(true);
          }}
        />
      ) : null}

      <GraphContextPanel
        open={ctxOpen}
        onClose={() => {
          setCtxOpen(false);
          setCtxEntityId(null);
          setCtxNodeHint(null);
        }}
        tenantId={tenantId}
        entityId={ctxEntityId}
        nodeHint={ctxNodeHint ?? undefined}
      />

      {graphPayload && graphPayload.nodes.length === 0 && !loading && !error ? (
        <p className="text-sm text-gray-500">Subgraph returned no nodes for this entity and depth.</p>
      ) : null}
    </div>
  );
}
