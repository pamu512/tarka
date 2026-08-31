import type { GraphEdge, GraphNode, GraphObjectAttention, GraphPathExplanation } from "../api/client";
import { pruneSubgraphForLinkView, undirectedLinkKey } from "./linkAnalysisGraph";

export type WorkspaceFilter = {
  types: string[] | null;
  minRisk: number | null;
  scoredOnly: boolean;
  growthOnly: boolean;
};

export const HUNT_LOOKBACK_DEFAULT_DAYS = 90;
export const HUNT_LOOKBACK_MAX_DAYS = 2555;
export const HUNT_SEED_MAX = 25;

export function parseGraphWorkspaceParams(
  sp: URLSearchParams,
  defaultTenant: string,
): { entityId: string; tenantId: string; depth: number; lookbackDays: number; decisionId: string } {
  const entityId = sp.get("entity_id") || sp.get("entity") || "";
  const tenantId = sp.get("tenant_id") || sp.get("tenant") || defaultTenant;
  const parsed = Number.parseInt(sp.get("depth") ?? "", 10);
  const depth = Number.isFinite(parsed) ? Math.min(5, Math.max(1, parsed)) : 2;
  const rawLb = Number.parseInt(sp.get("lookback_days") ?? "", 10);
  const lookbackDays = Number.isFinite(rawLb)
    ? Math.min(HUNT_LOOKBACK_MAX_DAYS, Math.max(1, rawLb))
    : HUNT_LOOKBACK_DEFAULT_DAYS;
  const decisionId = (sp.get("decision_id") || "").trim();
  return { entityId, tenantId, depth, lookbackDays, decisionId };
}

export function primaryLabel(labels: string[] | undefined): string {
  return labels?.[0] || "Custom";
}

/** Last evaluate stamp when no Decision vertex is selected. */
export function decisionToastText(node: GraphNode | null | undefined): string | null {
  const raw = node?.properties?.last_outcome;
  const outcome = typeof raw === "string" ? raw.trim() : "";
  return outcome || null;
}

export type LastOutcomeLabel = "deny" | "review" | "flag" | "allow" | "unknown";

export function lastOutcomeLabel(
  source:
    | { properties?: Record<string, unknown> | null; last_outcome?: unknown }
    | null
    | undefined,
): LastOutcomeLabel {
  const raw = source?.last_outcome ?? source?.properties?.last_outcome;
  const token = typeof raw === "string" ? raw.trim().toLowerCase() : "";
  if (token === "deny" || token === "review" || token === "flag" || token === "allow") return token;
  return "unknown";
}

/** Canvas class. Unknown is not the allow color. */
export function outcomePaintClass(label: LastOutcomeLabel): string {
  switch (label) {
    case "deny":
      return "hunt-outcome-deny";
    case "review":
    case "flag":
      return "hunt-outcome-review";
    case "allow":
      return "hunt-outcome-allow";
    default:
      return "hunt-outcome-unknown";
  }
}

export function graphLaggedEvaluate(
  latest: { trace_id?: string | null } | null | undefined,
  history: { last_trace_id?: string | null; trace_ids?: string[] } | null | undefined,
): boolean {
  const tid = String(latest?.trace_id || "").trim();
  if (!tid) return false;
  const last = String(history?.last_trace_id || "").trim();
  if (tid === last) return false;
  const ids = new Set((history?.trace_ids || []).map((x) => String(x || "").trim()).filter(Boolean));
  return !ids.has(tid);
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

const HUNT_INSTRUMENT_LABELS = new Set([
  "Device",
  "Place",
  "Payment",
  "Document",
  "LicensePlate",
  "Ip",
  "Email",
  "Phone",
  "Card",
  "Address",
]);
const HUNT_HIERARCHY_EXPAND_CAP = 8;
const HUNT_RECEIPT_LABELS = new Set(["Login", "Session", "Decision"]);
const HUNT_SEED_LABELS = new Set([...HUNT_INSTRUMENT_LABELS, "Decision"]);

function hopTimeMs(node: GraphNode): number | null {
  const props = node.properties || {};
  for (const key of ["created_at", "observed_at", "last_seen", "updated_at"] as const) {
    const raw = props[key];
    if (typeof raw !== "string" || !raw.trim()) continue;
    const ms = Date.parse(raw);
    if (Number.isFinite(ms)) return ms;
  }
  return null;
}

function nodeOutcome(node: GraphNode): LastOutcomeLabel {
  const fromLast = lastOutcomeLabel(node);
  if (fromLast !== "unknown") return fromLast;
  return lastOutcomeLabel({ last_outcome: node.properties?.outcome });
}

function outcomeRank(label: LastOutcomeLabel): number {
  if (label === "deny" || label === "review") return 3;
  if (label === "flag") return 2;
  if (label === "allow") return 0;
  return 1;
}

export function filterReceiptLookback(
  nodes: GraphNode[],
  edges: GraphEdge[],
  opts: { seedId: string; lookbackDays: number; nowMs: number },
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const since = opts.nowMs - opts.lookbackDays * 86_400_000;
  const drop = new Set<string>();
  for (const node of nodes) {
    if (node.id === opts.seedId) continue;
    if (!HUNT_RECEIPT_LABELS.has(primaryLabel(node.labels))) continue;
    const t = hopTimeMs(node);
    if (t != null && t < since) drop.add(node.id);
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

export function seedInstrumentFanout(
  seedId: string,
  nodes: GraphNode[],
  edges: GraphEdge[],
  attention: GraphObjectAttention[] | null | undefined,
  opts: { nowMs: number; lookbackDays: number; max: number; pinDecisionId?: string },
): { ids: string[]; total: number } {
  const windowed = filterReceiptLookback(nodes, edges, {
    seedId,
    lookbackDays: opts.lookbackDays,
    nowMs: opts.nowMs,
  });
  const byId = new Map(windowed.nodes.map((node) => [node.id, node]));
  const att = new Map((attention || []).map((row) => [row.entity_id, row]));
  const seen = new Set<string>();
  const candidates: GraphNode[] = [];
  for (const edge of windowed.edges) {
    const { from, to } = linkEndIds(edge);
    const other = from === seedId ? to : to === seedId ? from : "";
    if (!other || other === seedId || seen.has(other)) continue;
    const node = byId.get(other);
    if (!node || !HUNT_SEED_LABELS.has(primaryLabel(node.labels))) continue;
    seen.add(other);
    candidates.push(node);
  }
  const pin = (opts.pinDecisionId || "").trim();
  const ranked = [...candidates].sort((a, b) => compareHuntNeighbor(b, a, att));
  const picked: GraphNode[] = [];
  let haveDecision = false;
  for (const node of ranked) {
    const isDec = primaryLabel(node.labels) === "Decision";
    if (isDec) {
      if (haveDecision) continue;
      if (pin && node.id !== pin) continue;
      haveDecision = true;
    }
    picked.push(node);
  }
  if (pin && !haveDecision) {
    const pinned = byId.get(pin);
    if (pinned && primaryLabel(pinned.labels) === "Decision") picked.unshift(pinned);
  }
  const ids = picked.slice(0, Math.max(1, opts.max)).map((node) => node.id);
  return { ids, total: candidates.length };
}

function compareHuntNeighbor(
  a: GraphNode,
  b: GraphNode,
  att: Map<string, GraphObjectAttention>,
): number {
  const aa = att.get(a.id);
  const ba = att.get(b.id);
  const ap = aa?.attend_pack ? 1 : 0;
  const bp = ba?.attend_pack ? 1 : 0;
  if (ap !== bp) return ap - bp;
  const ai = aa?.importance ?? -1;
  const bi = ba?.importance ?? -1;
  if (ai !== bi) return ai - bi;
  const ao = outcomeRank(nodeOutcome(a));
  const bo = outcomeRank(nodeOutcome(b));
  if (ao !== bo) return ao - bo;
  return (hopTimeMs(a) ?? 0) - (hopTimeMs(b) ?? 0);
}

/** Mid-tier neighbors to fan out so Person Hunt sees IP + Decision (AGE is depth 1). */
export function hierarchyInstrumentFanout(
  seedId: string,
  nodes: GraphNode[],
  edges: GraphEdge[],
): { ids: string[]; total: number } {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const seen = new Set<string>();
  const all: string[] = [];
  for (const edge of edges) {
    const { from, to } = linkEndIds(edge);
    const other = from === seedId ? to : to === seedId ? from : "";
    if (!other || other === seedId || seen.has(other)) continue;
    if (!HUNT_INSTRUMENT_LABELS.has(primaryLabel(byId.get(other)?.labels))) continue;
    seen.add(other);
    all.push(other);
  }
  const ids = [...all].sort((a, b) => a.localeCompare(b)).slice(0, HUNT_HIERARCHY_EXPAND_CAP);
  return { ids, total: all.length };
}

export function hierarchyInstrumentIds(seedId: string, nodes: GraphNode[], edges: GraphEdge[]): string[] {
  return hierarchyInstrumentFanout(seedId, nodes, edges).ids;
}

/** Person canvas: instrument 1-hops merged in. Login stays when expand asked for it. */
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
  return mergeSubgraphs(seedId, seedSub, extra, maxNodes);
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
