/**
 * Semantic pruning + layout for evidence graph snapshots (React Flow).
 * Super-nodes (degree > 15) collapse excess **leaf** neighbors into one bundle node to cap DOM size.
 * Structural neighbors beyond the first 15 keep their vertices but hub→vertex edges are folded into the bundle chip (no duplicate spokes).
 */

import type { Edge, Node } from "@xyflow/react";

import {
  DEVICE_CLUSTER_GRAPH_LABEL,
  clusterSnapshotRaw,
  isSyntheticDeviceClusterId,
} from "../../utils/entityDeviceClustering";
import type { GraphSnapshotLink, GraphSnapshotNode } from "./snapshotGraphTypes";

/** Undirected: count distinct neighbors per node id. */
export const SUPER_NODE_DEGREE_THRESHOLD = 15;
/** Max individual spokes drawn from a single super-node (excluding the synthetic bundle edge). */
export const MAX_VISIBLE_SPOKES_PER_SUPER = 15;

export type SnapshotNodeData = { label: string; kind: string };
export type SnapshotBundleData = {
  label: string;
  kind: string;
  bundledLeafCount: number;
  structuralOverflowCount: number;
  bundledIdsPreview: string[];
};
export type SnapshotDeviceClusterData = {
  label: string;
  kind: string;
  memberCount: number;
  hashPreview: string;
  memberIdsPreview: string[];
};
export type SnapshotRfNode = Node<SnapshotNodeData, "snapshot">;
export type SnapshotBundleRfNode = Node<SnapshotBundleData, "snapshotBundle">;
export type SnapshotDeviceClusterRfNode = Node<SnapshotDeviceClusterData, "snapshotDeviceCluster">;
export type AnySnapshotRfNode = SnapshotRfNode | SnapshotBundleRfNode | SnapshotDeviceClusterRfNode;

/** Fixed dimensions so React Flow can skip off-screen nodes without measuring DOM (XYFlow 12+). */
export const SNAPSHOT_FLOW_DIM = {
  snapshot: { width: 148, height: 56 },
  snapshotBundle: { width: 176, height: 82 },
  snapshotDeviceCluster: { width: 168, height: 72 },
} as const;

export function snapshotRfNodeDimensions(n: AnySnapshotRfNode): { width: number; height: number } {
  if (n.type === "snapshotBundle") return SNAPSHOT_FLOW_DIM.snapshotBundle;
  if (n.type === "snapshotDeviceCluster") return SNAPSHOT_FLOW_DIM.snapshotDeviceCluster;
  return SNAPSHOT_FLOW_DIM.snapshot;
}

function sortIds(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true });
}

/** Build undirected adjacency (no multi-edges in Set). */
export function buildAdjacency(
  nodeIds: string[],
  links: GraphSnapshotLink[],
): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  const ensure = (id: string) => {
    if (!adj.has(id)) adj.set(id, new Set());
    return adj.get(id)!;
  };
  for (const id of nodeIds) ensure(id);
  for (const e of links) {
    const s = String(e.source);
    const t = String(e.target);
    if (s === t) continue;
    if (!adj.has(s) || !adj.has(t)) continue;
    ensure(s).add(t);
    ensure(t).add(s);
  }
  return adj;
}

/**
 * Split neighbors of a super-node:
 * - `visible` — endpoints we keep as direct hub spokes (max 15): prefer structural neighbors, then leaves.
 * - `bundledLeaves` — leaf neighbors not given a spoke (removed from graph if only adjacent to hub).
 * - `structuralOverflow` — structural neighbors not given a direct spoke (vertex kept; hub edge omitted).
 */
export function partitionSuperNodeNeighbors(
  adj: Map<string, Set<string>>,
  hubId: string,
): { visible: string[]; bundledLeaves: string[]; structuralOverflow: string[] } {
  const nbr = [...(adj.get(hubId) ?? [])].sort(sortIds);
  const structural: string[] = [];
  const leaves: string[] = [];
  for (const n of nbr) {
    const deg = adj.get(n)?.size ?? 0;
    if (deg > 1) structural.push(n);
    else leaves.push(n);
  }
  structural.sort(sortIds);
  leaves.sort(sortIds);

  const cap = MAX_VISIBLE_SPOKES_PER_SUPER;
  let visible: string[] = [];
  let bundledLeaves: string[] = [];
  let structuralOverflow: string[] = [];

  if (structural.length <= cap) {
    visible = structural.concat(leaves.slice(0, cap - structural.length));
    bundledLeaves = leaves.slice(cap - structural.length);
    return { visible, bundledLeaves, structuralOverflow };
  }

  visible = structural.slice(0, cap);
  structuralOverflow = structural.slice(cap);
  bundledLeaves = leaves;
  return { visible, bundledLeaves, structuralOverflow };
}

const BUNDLE_PREFIX = "snapshot-bundle:";

export function isBundleNodeId(id: string): boolean {
  return id.startsWith(BUNDLE_PREFIX);
}

export function bundleNodeIdForHub(hubId: string): string {
  return `${BUNDLE_PREFIX}${hubId}`;
}

export function hubIdFromBundleNodeId(bundleId: string): string | null {
  if (!isBundleNodeId(bundleId)) return null;
  return bundleId.slice(BUNDLE_PREFIX.length);
}

function edgeKeyUndirected(a: string, b: string): string {
  return a < b ? `${a}||${b}` : `${b}||${a}`;
}

/**
 * Apply semantic pruning: trim hub fan-out, optional bundle node per super-hub.
 */
export function pruneSuperNodeFans(params: {
  rawNodes: GraphSnapshotNode[];
  rawLinks: GraphSnapshotLink[];
}): {
  nodesOut: GraphSnapshotNode[];
  linksOut: GraphSnapshotLink[];
  bundleMeta: Map<
    string,
    { bundledLeafIds: string[]; structuralOverflowIds: string[] }
  >;
} {
  const { rawNodes, rawLinks } = params;
  const idSet = new Set(rawNodes.map((n) => String(n.id)));
  const linksSanitized = rawLinks.filter(
    (e) => idSet.has(String(e.source)) && idSet.has(String(e.target)),
  );
  const nodeIds = [...idSet];
  const adj = buildAdjacency(nodeIds, linksSanitized);
  const degree = new Map<string, number>();
  for (const id of nodeIds) {
    degree.set(id, adj.get(id)?.size ?? 0);
  }

  const superHubs = nodeIds.filter((id) => (degree.get(id) ?? 0) > SUPER_NODE_DEGREE_THRESHOLD);
  if (superHubs.length === 0) {
    return {
      nodesOut: rawNodes,
      linksOut: linksSanitized,
      bundleMeta: new Map(),
    };
  }

  const removeIds = new Set<string>();
  const dropEdges = new Set<string>();
  const bundleMeta = new Map<
    string,
    { bundledLeafIds: string[]; structuralOverflowIds: string[] }
  >();

  for (const hub of superHubs) {
    const { visible, bundledLeaves, structuralOverflow } = partitionSuperNodeNeighbors(adj, hub);
    const vis = new Set(visible);

    for (const other of adj.get(hub) ?? []) {
      if (!vis.has(other)) {
        dropEdges.add(edgeKeyUndirected(hub, other));
      }
    }

    for (const leaf of bundledLeaves) {
      if ((adj.get(leaf)?.size ?? 0) === 1) {
        removeIds.add(leaf);
      }
    }

    const leafCollapsed = bundledLeaves.filter((id) => removeIds.has(id));
    if (leafCollapsed.length > 0 || structuralOverflow.length > 0) {
      bundleMeta.set(hub, {
        bundledLeafIds: leafCollapsed.sort(sortIds),
        structuralOverflowIds: structuralOverflow.sort(sortIds),
      });
    }
  }

  const nodesOut = rawNodes.filter((n) => !removeIds.has(String(n.id)));
  const kept = new Set(nodesOut.map((n) => String(n.id)));

  const linksOut: GraphSnapshotLink[] = [];
  for (const e of linksSanitized) {
    const s = String(e.source);
    const t = String(e.target);
    if (!kept.has(s) || !kept.has(t)) continue;
    if (dropEdges.has(edgeKeyUndirected(s, t))) continue;
    linksOut.push(e);
  }

  const extraNodes: GraphSnapshotNode[] = [];
  for (const [hub, meta] of bundleMeta) {
    const bid = bundleNodeIdForHub(hub);
    const nLeaf = meta.bundledLeafIds.length;
    const nStruct = meta.structuralOverflowIds.length;
    const total = nLeaf + nStruct;
    const label =
      nStruct > 0 && nLeaf > 0
        ? `+${total} hidden (${nLeaf} leaf, ${nStruct} linked)`
        : nStruct > 0
          ? `+${total} linked elsewhere`
          : `+${total} leaf`;
    extraNodes.push({
      id: bid,
      kind: "Group",
      label,
    });
    linksOut.push({ source: hub, target: bid, rel: "collapsed" });
  }

  return {
    nodesOut: nodesOut.concat(extraNodes),
    linksOut,
    bundleMeta,
  };
}

/** Layered layout: hubs left, neighbors middle, bundles inset, orphans grid right. */
export function layoutSnapshotNodes(
  rfNodes: Array<AnySnapshotRfNode>,
  edges: Edge[],
): AnySnapshotRfNode[] {
  if (rfNodes.length === 0) return rfNodes;

  const adj = new Map<string, Set<string>>();
  const touch = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, new Set());
    if (!adj.has(b)) adj.set(b, new Set());
    adj.get(a)!.add(b);
    adj.get(b)!.add(a);
  };
  for (const e of edges) {
    touch(e.source, e.target);
  }

  const deg = new Map<string, number>();
  for (const n of rfNodes) {
    deg.set(n.id, adj.get(n.id)?.size ?? 0);
  }

  const colHub = 40;
  const colNbr = 280;
  const colBundle = 200;
  const rowGap = 86;
  const hubBlock = 160;

  const supers = rfNodes
    .filter((n) => (deg.get(n.id) ?? 0) > SUPER_NODE_DEGREE_THRESHOLD && n.type === "snapshot")
    .map((n) => n.id)
    .sort(sortIds);

  const placed = new Map<string, { x: number; y: number }>();

  supers.forEach((hid, hubIdx) => {
    const y0 = hubIdx * hubBlock;
    placed.set(hid, { x: colHub, y: y0 });

    const bid = bundleNodeIdForHub(hid);
    if (rfNodes.some((n) => n.id === bid)) {
      placed.set(bid, { x: colBundle, y: y0 + rowGap * 0.35 });
    }

    const nbr = [...(adj.get(hid) ?? [])]
      .filter((x) => !isBundleNodeId(x))
      .sort(sortIds);

    let row = 0;
    for (const nb of nbr) {
      if (placed.has(nb)) continue;
      placed.set(nb, { x: colNbr, y: y0 + row * rowGap });
      row += 1;
    }
  });

  let gi = 0;
  const orphanCol = 460;
  const orphanRow = 96;
  for (const n of rfNodes) {
    if (placed.has(n.id)) continue;
    placed.set(n.id, {
      x: orphanCol + (gi % 4) * 190,
      y: Math.floor(gi / 4) * orphanRow,
    });
    gi += 1;
  }

  return rfNodes.map((n) => {
    const dim = snapshotRfNodeDimensions(n);
    return {
      ...n,
      width: dim.width,
      height: dim.height,
      position: placed.get(n.id) ?? n.position,
    };
  });
}

export type ParseGraphSnapshotOptions = {
  /** Collapse vertices that share ``device_hash`` before hub pruning (Prompt 161). */
  clusterByDeviceHash?: boolean;
};

/**
 * Parse persisted snapshot JSON → semantically pruned, laid-out React Flow elements.
 */
export function parseGraphSnapshot(
  snapshot: unknown,
  options?: ParseGraphSnapshotOptions,
): {
  nodes: AnySnapshotRfNode[];
  edges: Edge[];
} {
  if (snapshot == null || typeof snapshot !== "object") {
    return { nodes: [], edges: [] };
  }
  const o = snapshot as Record<string, unknown>;
  let rawNodes = Array.isArray(o.nodes) ? (o.nodes as GraphSnapshotNode[]) : [];
  let rawLinks: GraphSnapshotLink[] = Array.isArray(o.links)
    ? (o.links as GraphSnapshotLink[])
    : Array.isArray(o.edges)
      ? (o.edges as GraphSnapshotLink[])
      : [];

  if (options?.clusterByDeviceHash && rawNodes.length > 0) {
    const clustered = clusterSnapshotRaw(rawNodes, rawLinks);
    rawNodes = clustered.nodes;
    rawLinks = clustered.links;
  }

  const pruned = pruneSuperNodeFans({ rawNodes, rawLinks });
  const { bundleMeta } = pruned;

  const rfNodes: AnySnapshotRfNode[] = pruned.nodesOut.map((n) => {
    const id = String(n.id);
    if (isBundleNodeId(id)) {
      const hub = hubIdFromBundleNodeId(id);
      const meta = hub ? bundleMeta.get(hub) : undefined;
      const preview = [
        ...(meta?.bundledLeafIds ?? []),
        ...(meta?.structuralOverflowIds ?? []),
      ].slice(0, 10);
      const leafC = meta?.bundledLeafIds.length ?? 0;
      const structC = meta?.structuralOverflowIds.length ?? 0;
      const fallbackLabel =
        structC > 0 && leafC > 0
          ? `+${leafC + structC} hidden (${leafC} leaf, ${structC} linked)`
          : structC > 0
            ? `+${structC} linked elsewhere`
            : `+${leafC} leaf`;
      const label =
        n.label != null && String(n.label).trim() !== "" ? String(n.label) : fallbackLabel;
      return {
        id,
        type: "snapshotBundle",
        position: { x: 0, y: 0 },
        data: {
          label,
          kind: "Group",
          bundledLeafCount: leafC,
          structuralOverflowCount: structC,
          bundledIdsPreview: preview,
        },
      };
    }
    const props = n.properties ?? {};
    const isDeviceCluster =
      n.kind === DEVICE_CLUSTER_GRAPH_LABEL ||
      isSyntheticDeviceClusterId(id) ||
      props.cluster_kind === "device_hash";
    if (isDeviceCluster) {
      const rawMembers = typeof props.cluster_member_ids === "string" ? props.cluster_member_ids : "";
      const memberIdsPreview = rawMembers
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .slice(0, 12);
      const memberCount =
        typeof props.cluster_member_count === "number" && Number.isFinite(props.cluster_member_count)
          ? props.cluster_member_count
          : memberIdsPreview.length || 2;
      const hashRaw =
        (typeof props.device_hash === "string" && props.device_hash) ||
        (typeof n.device_hash === "string" && n.device_hash) ||
        "";
      const hashPreview =
        hashRaw.length > 28 ? `${hashRaw.slice(0, 12)}…${hashRaw.slice(-10)}` : hashRaw || "—";
      const label =
        n.label != null && String(n.label).trim() !== ""
          ? String(n.label)
          : `${memberCount} entities · shared device`;
      return {
        id,
        type: "snapshotDeviceCluster",
        position: { x: 0, y: 0 },
        data: {
          label,
          kind: DEVICE_CLUSTER_GRAPH_LABEL,
          memberCount,
          hashPreview,
          memberIdsPreview,
        },
      };
    }
    return {
      id,
      type: "snapshot",
      position: { x: 0, y: 0 },
      data: {
        label: n.label != null && String(n.label).trim() !== "" ? String(n.label) : String(n.id),
        kind: n.kind != null && String(n.kind).trim() !== "" ? String(n.kind) : "Node",
      },
    };
  });

  const edges: Edge[] = pruned.linksOut.map((e, i) => ({
    id: `snapshot-edge-${i}-${String(e.source)}-${String(e.target)}`,
    source: String(e.source),
    target: String(e.target),
    label: e.rel != null ? String(e.rel) : undefined,
  }));

  return {
    nodes: layoutSnapshotNodes(rfNodes, edges),
    edges,
  };
}
