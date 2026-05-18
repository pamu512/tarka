/**
 * Link-analysis helpers: subgraph pruning (large JanusGraph neighborhoods) and
 * risk score normalization for force-graph nodes.
 */

import type { EntityRiskResult, GraphEdge, GraphNode, RiskPropagationResult } from "../api/client";

/** Maximum entities to send to the force layout (performance budget). */
export const LINK_ANALYSIS_MAX_NODES = 3000;

/** Minimal node shape for pruning (matches ``GraphNode``; safe for web workers). */
export type LinkPruneNode = { id: string; labels: string[]; properties: Record<string, unknown> };

/** Minimal edge shape for pruning (matches ``GraphEdge``). */
export type LinkPruneEdge = {
  from_id: string;
  to_id: string;
  type: string;
  properties?: Record<string, unknown>;
};

export type PruneSubgraphResult<N = LinkPruneNode, E = LinkPruneEdge> = {
  nodes: N[];
  edges: E[];
  originalNodeCount: number;
  prunedNodeCount: number;
};

function degreeMap<N extends { id: string }, E extends { from_id: string; to_id: string }>(
  nodes: N[],
  edges: E[],
): Map<string, number> {
  const m = new Map<string, number>();
  for (const n of nodes) {
    m.set(n.id, 0);
  }
  for (const e of edges) {
    if (m.has(e.from_id)) m.set(e.from_id, (m.get(e.from_id) ?? 0) + 1);
    if (m.has(e.to_id)) m.set(e.to_id, (m.get(e.to_id) ?? 0) + 1);
  }
  return m;
}

/**
 * If the subgraph exceeds ``maxNodes``, keep the seed entity and the highest-degree
 * neighbors until the cap. Drops dangling edges. Deterministic tie-break by id.
 */
export function pruneSubgraphForLinkView<N extends LinkPruneNode, E extends LinkPruneEdge>(
  nodes: N[],
  edges: E[],
  seedEntityId: string,
  maxNodes: number,
): PruneSubgraphResult<N, E> {
  const originalNodeCount = nodes.length;
  if (nodes.length <= maxNodes) {
    const idSet = new Set(nodes.map((n) => n.id));
    const filteredEdges = edges.filter((e) => idSet.has(e.from_id) && idSet.has(e.to_id));
    return {
      nodes,
      edges: filteredEdges,
      originalNodeCount,
      prunedNodeCount: nodes.length,
    };
  }

  const idSetAll = new Set(nodes.map((n) => n.id));
  const validEdges = edges.filter((e) => idSetAll.has(e.from_id) && idSetAll.has(e.to_id));
  const deg = degreeMap(nodes, validEdges);
  const seed = idSetAll.has(seedEntityId) ? seedEntityId : nodes[0]?.id ?? "";
  const others = nodes.map((n) => n.id).filter((id) => id !== seed);
  others.sort((a, b) => {
    const da = deg.get(a) ?? 0;
    const db = deg.get(b) ?? 0;
    if (db !== da) return db - da;
    return a.localeCompare(b);
  });
  const keepIds = new Set<string>();
  if (seed) keepIds.add(seed);
  for (const id of others) {
    if (keepIds.size >= maxNodes) break;
    keepIds.add(id);
  }
  const keptNodes = nodes.filter((n) => keepIds.has(n.id));
  const keptEdges = validEdges.filter((e) => keepIds.has(e.from_id) && keepIds.has(e.to_id));
  return {
    nodes: keptNodes,
    edges: keptEdges,
    originalNodeCount,
    prunedNodeCount: keptNodes.length,
  };
}

/** Normalize backend risk to a 0–100 display score, or null if unknown. */
export function normalizeRiskScore(raw: number | null | undefined): number | null {
  if (raw === null || raw === undefined || Number.isNaN(raw)) return null;
  if (raw <= 1 && raw >= 0) return Math.round(raw * 1000) / 10;
  if (raw >= 0 && raw <= 100) return Math.round(raw * 10) / 10;
  return Math.max(0, Math.min(100, raw));
}

function numericFromUnknown(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const t = v.trim();
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** Pull an optional risk value from JanusGraph vertex properties (if present). */
export function riskFromNodeProperties(properties: Record<string, unknown>): number | null {
  const keys = [
    "risk_score",
    "riskScore",
    "propagated_risk_score",
    "propagated_risk",
    "graph_risk_score",
    "score",
  ] as const;
  for (const k of keys) {
    const n = numericFromUnknown(properties[k]);
    if (n !== null) return normalizeRiskScore(n);
  }
  return null;
}

export type LinkAnalysisGraphNode = GraphNode & {
  /** 0–100 display risk; null when analytics did not supply a score. */
  displayRisk: number | null;
};

export function buildRiskScoreByEntityId(
  anchor: EntityRiskResult | null,
  propagationEntities: RiskPropagationResult[],
): Map<string, number> {
  const out = new Map<string, number>();
  if (anchor?.entity_id) {
    const v = normalizeRiskScore(anchor.risk_score);
    if (v !== null) out.set(anchor.entity_id, v);
  }
  for (const row of propagationEntities) {
    const v = normalizeRiskScore(row.propagated_risk_score);
    if (v !== null && row.entity_id) out.set(row.entity_id, v);
  }
  return out;
}

/** Merge subgraph nodes with analytics + vertex properties (properties as lowest priority). */
export function attachDisplayRiskToNodes(
  nodes: GraphNode[],
  analyticsById: Map<string, number>,
): LinkAnalysisGraphNode[] {
  return nodes.map((n) => {
    const fromApi = analyticsById.get(n.id);
    const fromProps = riskFromNodeProperties(n.properties ?? {});
    const displayRisk = fromApi ?? fromProps ?? null;
    return { ...n, displayRisk };
  });
}

export function toForceGraphLinks(edges: LinkPruneEdge[]): { source: string; target: string; relType: string }[] {
  return edges.map((e) => ({
    source: e.from_id,
    target: e.to_id,
    relType: e.type,
  }));
}
