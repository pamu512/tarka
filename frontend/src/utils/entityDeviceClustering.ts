import type { GraphEdge, GraphNode, SubgraphResponse } from "../api/client";
import type { GraphSnapshotLink, GraphSnapshotNode } from "../components/CaseView/snapshotGraphTypes";

/** Synthetic subgraph node id prefix — distinct from ``snapshot-bundle:`` (React Flow). */
export const DEVICE_CLUSTER_ID_PREFIX = "device-cluster:";

export const DEVICE_CLUSTER_GRAPH_LABEL = "DeviceCluster";

function normalizeHash(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  return t.length > 0 ? t : null;
}

/** Read ``device_hash`` / ``deviceHash`` from Janus-style ``properties``. */
export function deviceHashFromGraphProperties(properties: Record<string, unknown> | undefined): string | null {
  if (!properties) return null;
  return normalizeHash(properties.device_hash ?? properties.deviceHash);
}

export function deviceHashFromGraphNode(n: GraphNode): string | null {
  return deviceHashFromGraphProperties(n.properties);
}

function deviceHashFromSnapshotNode(n: GraphSnapshotNode): string | null {
  const o = n as Record<string, unknown>;
  const direct = normalizeHash(o.device_hash ?? o.deviceHash);
  if (direct) return direct;
  const props = o.properties;
  if (props && typeof props === "object" && !Array.isArray(props)) {
    return normalizeHash((props as Record<string, unknown>).device_hash ?? (props as Record<string, unknown>).deviceHash);
  }
  return null;
}

function clusterIdForHash(hash: string): string {
  const safe = hash.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 128);
  return `${DEVICE_CLUSTER_ID_PREFIX}${safe}`;
}

export function isSyntheticDeviceClusterId(id: string): boolean {
  return id.startsWith(DEVICE_CLUSTER_ID_PREFIX);
}

function buildHashGroups<T extends { id: string }>(
  nodes: T[],
  getHash: (n: T) => string | null,
): Map<string, string[]> {
  const hashToMembers = new Map<string, string[]>();
  for (const n of nodes) {
    const h = getHash(n);
    if (!h) continue;
    if (!hashToMembers.has(h)) hashToMembers.set(h, []);
    hashToMembers.get(h)!.push(n.id);
  }
  return hashToMembers;
}

/**
 * Collapse entities that share the same ``device_hash`` (≥2 nodes) into one vertex and rewire edges.
 * Nodes without a hash, or with a unique hash, are unchanged.
 */
export function clusterSubgraphByDeviceHash(nodes: GraphNode[], edges: GraphEdge[]): SubgraphResponse {
  const hashToMembers = buildHashGroups(nodes, deviceHashFromGraphNode);
  const mergeHashes = [...hashToMembers.entries()].filter(([, ids]) => ids.length >= 2);
  if (mergeHashes.length === 0) {
    return { nodes, edges };
  }

  const memberToCluster = new Map<string, string>();
  const clusterNodes: GraphNode[] = [];
  for (const [hash, memberIds] of mergeHashes) {
    const cid = clusterIdForHash(hash);
    const sortedMembers = [...memberIds].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    for (const id of sortedMembers) memberToCluster.set(id, cid);
    clusterNodes.push({
      id: cid,
      labels: [DEVICE_CLUSTER_GRAPH_LABEL],
      properties: {
        device_hash: hash,
        cluster_member_count: sortedMembers.length,
        cluster_member_ids: sortedMembers.join(","),
        cluster_kind: "device_hash",
      },
    });
  }

  const keptNodes = nodes.filter((n) => !memberToCluster.has(n.id));
  const newNodes = [...keptNodes, ...clusterNodes];

  const remap = (id: string) => memberToCluster.get(id) ?? id;
  const edgeKeys = new Set<string>();
  const newEdges: GraphEdge[] = [];
  for (const e of edges) {
    const from = remap(e.from_id);
    const to = remap(e.to_id);
    if (from === to) continue;
    const key = `${from}|${to}|${e.type}`;
    if (edgeKeys.has(key)) continue;
    edgeKeys.add(key);
    newEdges.push({ ...e, from_id: from, to_id: to });
  }

  return { nodes: newNodes, edges: newEdges };
}

/**
 * Same grouping rules as ``clusterSubgraphByDeviceHash``, for persisted ``graph_snapshot`` wire JSON.
 */
export function clusterSnapshotRaw(
  rawNodes: GraphSnapshotNode[],
  rawLinks: GraphSnapshotLink[],
): { nodes: GraphSnapshotNode[]; links: GraphSnapshotLink[] } {
  const hashToMembers = buildHashGroups(rawNodes, deviceHashFromSnapshotNode);
  const mergeHashes = [...hashToMembers.entries()].filter(([, ids]) => ids.length >= 2);
  if (mergeHashes.length === 0) {
    return { nodes: rawNodes, links: rawLinks };
  }

  const memberToCluster = new Map<string, string>();
  const clusterNodes: GraphSnapshotNode[] = [];
  for (const [hash, memberIds] of mergeHashes) {
    const cid = clusterIdForHash(hash);
    const sortedMembers = [...memberIds].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    for (const id of sortedMembers) memberToCluster.set(id, cid);
    clusterNodes.push({
      id: cid,
      kind: DEVICE_CLUSTER_GRAPH_LABEL,
      label: `${sortedMembers.length} entities · shared device`,
      device_hash: hash,
      properties: {
        device_hash: hash,
        cluster_member_count: sortedMembers.length,
        cluster_member_ids: sortedMembers.join(","),
        cluster_kind: "device_hash",
      },
    });
  }

  const keptNodes = rawNodes.filter((n) => !memberToCluster.has(String(n.id)));
  const nodesOut = [...keptNodes, ...clusterNodes];

  const remap = (id: string) => memberToCluster.get(id) ?? id;
  const edgeKeys = new Set<string>();
  const linksOut: GraphSnapshotLink[] = [];
  for (const e of rawLinks) {
    const s = remap(String(e.source));
    const t = remap(String(e.target));
    if (s === t) continue;
    const rel = e.rel != null ? String(e.rel) : "";
    const key = `${s}|${t}|${rel}`;
    if (edgeKeys.has(key)) continue;
    edgeKeys.add(key);
    linksOut.push({ ...e, source: s, target: t });
  }

  return { nodes: nodesOut, links: linksOut };
}
