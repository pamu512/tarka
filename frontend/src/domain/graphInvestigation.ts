import type { GraphEdge, GraphNode, GraphPathExplanation } from "../api/client";
import { pruneSubgraphForLinkView, undirectedLinkKey } from "./linkAnalysisGraph";

export type WorkspaceFilter = {
  types: string[] | null;
  minRisk: number | null;
  scoredOnly: boolean;
  growthOnly: boolean;
};

export function parseGraphWorkspaceParams(
  sp: URLSearchParams,
  defaultTenant: string,
): { entityId: string; tenantId: string; depth: number } {
  const entityId = sp.get("entity_id") || sp.get("entity") || "";
  const tenantId = sp.get("tenant_id") || sp.get("tenant") || defaultTenant;
  const parsed = Number.parseInt(sp.get("depth") ?? "", 10);
  const depth = Number.isFinite(parsed) ? Math.min(5, Math.max(1, parsed)) : 2;
  return { entityId, tenantId, depth };
}

export function primaryLabel(labels: string[] | undefined): string {
  return labels?.[0] || "Custom";
}

export function storedDisplayRisk(node: GraphNode): number | null {
  if (node.scored === false) return null;
  if (node.scored === true) {
    const v = node.risk_score;
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  }
  const v = node.risk_score;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return null;
}

export function typeHistogram(nodes: GraphNode[]): Array<{ label: string; count: number }> {
  const counts = new Map<string, number>();
  for (const node of nodes) {
    const label = primaryLabel(node.labels);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

function readNumericField(node: GraphNode, key: "relation_growth_1h" | "relation_growth_24h"): number | null {
  const top = node[key];
  if (typeof top === "number" && Number.isFinite(top)) return top;
  const nested = node.properties?.[key];
  if (typeof nested === "number" && Number.isFinite(nested)) return nested;
  return null;
}

function keepWorkspaceNode(node: GraphNode, opts: WorkspaceFilter): boolean {
  if (opts.types !== null && !opts.types.includes(primaryLabel(node.labels))) return false;

  const risk = storedDisplayRisk(node);
  const unscored = node.scored === false || risk === null;
  if (opts.scoredOnly && unscored) return false;
  if (opts.minRisk != null && !unscored && risk < opts.minRisk) return false;

  if (opts.growthOnly) {
    const g1 = readNumericField(node, "relation_growth_1h");
    const g24 = readNumericField(node, "relation_growth_24h");
    if (!((g1 != null && g1 >= 5) || (g24 != null && g24 >= 15))) return false;
  }
  return true;
}

export function filterWorkspaceNodes(
  nodes: GraphNode[],
  edges: GraphEdge[],
  opts: WorkspaceFilter,
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const kept = nodes.filter((node) => keepWorkspaceNode(node, opts));
  const ids = new Set(kept.map((node) => node.id));
  return {
    nodes: kept,
    edges: edges.filter((edge) => ids.has(edge.from_id) && ids.has(edge.to_id)),
  };
}

export function mergeSubgraphs(
  seedId: string,
  base: { nodes: GraphNode[]; edges: GraphEdge[] },
  extra: { nodes: GraphNode[]; edges: GraphEdge[] },
  maxNodes: number,
): { nodes: GraphNode[]; edges: GraphEdge[]; originalNodeCount: number; prunedNodeCount: number } {
  const byId = new Map<string, GraphNode>();
  for (const node of base.nodes) byId.set(node.id, node);
  for (const node of extra.nodes) byId.set(node.id, node);

  const byKey = new Map<string, GraphEdge>();
  for (const edge of [...base.edges, ...extra.edges]) {
    const key = `${edge.from_id}\0${edge.to_id}\0${edge.type}`;
    if (!byKey.has(key)) byKey.set(key, edge);
  }

  return pruneSubgraphForLinkView([...byId.values()], [...byKey.values()], seedId, maxNodes);
}

export function pathNodeIds(expl: GraphPathExplanation, seedId: string, selectedId: string): Set<string> {
  const ids = new Set<string>([seedId, selectedId]);
  if (expl.subject) ids.add(expl.subject);
  if (expl.target) ids.add(expl.target);
  for (const p of expl.paths) {
    if (p.entity_id) ids.add(p.entity_id);
    if (p.target_entity_id) ids.add(p.target_entity_id);
    for (const hop of p.hops ?? []) {
      if (hop.entity_id) ids.add(hop.entity_id);
    }
  }
  return ids;
}

export function pathHighlightLinkKeys(expl: GraphPathExplanation): Set<string> {
  const keys = new Set<string>();
  for (const p of expl.paths ?? []) {
    const hops = p.hops ?? [];
    for (let i = 0; i < hops.length - 1; i++) {
      const a = hops[i]?.entity_id;
      const b = hops[i + 1]?.entity_id;
      if (!a || !b) continue;
      keys.add(undirectedLinkKey(a, b));
    }
  }
  return keys;
}
