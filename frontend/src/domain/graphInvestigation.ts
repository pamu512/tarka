import type { GraphEdge, GraphNode, GraphObjectAttention, GraphPathExplanation } from "../api/client";
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

/** Last evaluate on this object. Decisions are not graph nodes. */
export function decisionToastText(node: GraphNode | null | undefined): string | null {
  const raw = node?.properties?.last_outcome;
  const outcome = typeof raw === "string" ? raw.trim() : "";
  return outcome || null;
}

export function searchHitViaSubtitle(
  via: { entity_id: string; labels?: string[] | null } | null | undefined,
): string | null {
  const id = via?.entity_id?.trim() ?? "";
  if (!id) return null;
  const kind = via?.labels?.[0] || "Custom";
  return `via ${kind} ${id}`;
}

export function searchHitMatchedOn(matchedOn: string | null | undefined): string | null {
  const on = String(matchedOn || "").trim();
  if (!on || on === "external_id") return null;
  return on;
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

const HUNT_INSTRUMENT_LABELS = new Set(["Device", "Payment", "Document", "LicensePlate", "Ip"]);
const HUNT_HIERARCHY_EXPAND_CAP = 8;

/** Mid-tier neighbors to fan out so Person Hunt sees IP + Decision (AGE is depth 1). */
export function hierarchyInstrumentIds(seedId: string, nodes: GraphNode[], edges: GraphEdge[]): string[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const edge of edges) {
    const { from, to } = linkEndIds(edge);
    const other = from === seedId ? to : to === seedId ? from : "";
    if (!other || other === seedId || seen.has(other)) continue;
    if (!HUNT_INSTRUMENT_LABELS.has(primaryLabel(byId.get(other)?.labels))) continue;
    seen.add(other);
    ids.push(other);
    if (ids.length >= HUNT_HIERARCHY_EXPAND_CAP) break;
  }
  return ids.sort((a, b) => a.localeCompare(b));
}

function filterPersonHuntNoise(
  seedId: string,
  nodes: GraphNode[],
  edges: GraphEdge[],
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const seed = nodes.find((node) => node.id === seedId);
  const drop = new Set<string>();
  for (const node of nodes) {
    if (node.id === seedId) continue;
    const kind = primaryLabel(node.labels);
    if (kind === "Decision") drop.add(node.id);
    if (kind === "Login" && seed?.labels?.includes("Person")) drop.add(node.id);
  }

  const kept = nodes.filter((node) => !drop.has(node.id));
  const ids = new Set(kept.map((node) => node.id));
  return {
    nodes: kept,
    edges: edges.filter((edge) => {
      const { from, to } = linkEndIds(edge);
      return ids.has(from) && ids.has(to);
    }),
  };
}

/** Person canvas: instrument 1-hops merged in. Decision vertices stay off the graph. */
export function buildPersonHuntGraph(
  seedId: string,
  seedSub: { nodes: GraphNode[]; edges: GraphEdge[] },
  instrumentSubs: Array<{ nodes: GraphNode[]; edges: GraphEdge[] }>,
  maxNodes: number,
): { nodes: GraphNode[]; edges: GraphEdge[]; originalNodeCount: number; prunedNodeCount: number } {
  const extra = {
    nodes: instrumentSubs.flatMap((sub) => sub.nodes),
    edges: instrumentSubs.flatMap((sub) => sub.edges),
  };
  const merged = mergeSubgraphs(seedId, seedSub, extra, maxNodes);
  const cleaned = filterPersonHuntNoise(seedId, merged.nodes, merged.edges);
  return {
    nodes: cleaned.nodes,
    edges: cleaned.edges,
    originalNodeCount: merged.originalNodeCount,
    prunedNodeCount: cleaned.nodes.length,
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

const LAST_PERSON_KEY = "tarka.last_person_entity";

export function readLastPersonEntity(tenantId: string): string {
  try {
    const raw = localStorage.getItem(LAST_PERSON_KEY);
    if (!raw) return "";
    const parsed = JSON.parse(raw) as { tenant_id?: string; entity_id?: string };
    if (String(parsed.tenant_id || "") !== tenantId) return "";
    return String(parsed.entity_id || "").trim();
  } catch {
    return "";
  }
}

function isWeakHomeId(id: string): boolean {
  return id.startsWith("ip:");
}

function linkEndIds(edge: GraphEdge): { from: string; to: string } {
  const extra = edge as GraphEdge & { startNode?: unknown; endNode?: unknown };
  return {
    from: String(edge.from_id || extra.startNode || ""),
    to: String(edge.to_id || extra.endNode || ""),
  };
}

export function rankRelatedLinks(
  seedId: string,
  edges: GraphEdge[],
  attention: GraphObjectAttention[] | null | undefined,
): Array<{ edge: GraphEdge; other: string; attention: GraphObjectAttention | null }> {
  const byId = new Map((attention || []).map((row) => [row.entity_id, row]));
  return [...edges]
    .map((edge) => {
      const { from, to } = linkEndIds(edge);
      const other = from === seedId ? to : to === seedId ? from : from || to;
      return { edge, other, attention: byId.get(other) ?? null };
    })
    .filter((row) => row.other)
    .sort((a, b) => {
      const ai = a.attention?.importance ?? -1;
      const bi = b.attention?.importance ?? -1;
      if (bi !== ai) return bi - ai;
      return a.other.localeCompare(b.other);
    });
}

export function writeLastPersonEntity(tenantId: string, entityId: string): void {
  const tid = tenantId.trim();
  const id = entityId.trim();
  if (!tid || !id || isWeakHomeId(id)) return;
  try {
    localStorage.setItem(LAST_PERSON_KEY, JSON.stringify({ tenant_id: tid, entity_id: id }));
  } catch {
    // quota — desk still opens; next visit may not restore this person
  }
}

/** Entity is the key. Prefer the last person, then a Person row, then any object. */
export function pickHomePerson(opts: {
  lastEntityId?: string | null;
  rows?: Array<{ entity_id?: string; labels?: string[] }>;
}): string {
  const last = String(opts.lastEntityId || "").trim();
  if (last && !isWeakHomeId(last)) return last;
  const rows = opts.rows || [];
  const person = rows.find((r) => {
    const id = String(r.entity_id || "").trim();
    return id && !isWeakHomeId(id) && (r.labels || []).includes("Person");
  });
  if (person?.entity_id) return String(person.entity_id).trim();
  const any = rows.find((r) => {
    const id = String(r.entity_id || "").trim();
    return id && !isWeakHomeId(id);
  });
  return String(any?.entity_id || "").trim();
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
