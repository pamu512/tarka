import type { Edge, Node } from "@xyflow/react";

/** Extra flow-space margin beyond the pane so edges/nodes do not pop at the viewport edge. */
export const VIEWPORT_PRUNE_PADDING_PX = 96;

export type FlowViewport = { x: number; y: number; zoom: number };

export type Rect = { minX: number; maxX: number; minY: number; maxY: number };

/**
 * Visible region in **flow (graph) coordinates** for the current viewport.
 * Maps pane pixel corners through the inverse of translate(viewport) + scale(zoom).
 */
export function flowVisibleRect(
  viewport: FlowViewport,
  paneWidthPx: number,
  paneHeightPx: number,
  paddingPx: number,
): Rect {
  const { x: vx, y: vy, zoom } = viewport;
  const z = zoom <= 0 ? 1 : zoom;
  const pad = paddingPx / z;

  let minX = (0 - vx) / z;
  let maxX = (paneWidthPx - vx) / z;
  let minY = (0 - vy) / z;
  let maxY = (paneHeightPx - vy) / z;

  minX -= pad;
  maxX += pad;
  minY -= pad;
  maxY += pad;

  return { minX, maxX, minY, maxY };
}

function rectsIntersect(
  ax: number,
  ay: number,
  aw: number,
  ah: number,
  r: Rect,
): boolean {
  const bx1 = ax;
  const bx2 = ax + aw;
  const by1 = ay;
  const by2 = ay + ah;
  return bx1 <= r.maxX && bx2 >= r.minX && by1 <= r.maxY && by2 >= r.minY;
}

export type NodeSizeDefaults<NodeType extends Node = Node> = (
  node: NodeType,
) => { width: number; height: number };

/**
 * Keep nodes whose bounding box intersects the visible flow rect.
 * Keeps an edge only when **both** endpoints are kept (avoids danglingBezier artifacts).
 */
export function pruneNodesAndEdgesForViewport<NodeType extends Node = Node>(
  nodes: NodeType[],
  edges: Edge[],
  viewport: FlowViewport,
  paneWidthPx: number,
  paneHeightPx: number,
  getDefaultSize: NodeSizeDefaults<NodeType>,
  paddingPx = VIEWPORT_PRUNE_PADDING_PX,
): { nodes: NodeType[]; edges: Edge[] } {
  if (nodes.length === 0) {
    return { nodes: [], edges: [] };
  }

  if (paneWidthPx < 16 || paneHeightPx < 16) {
    return { nodes, edges };
  }

  const rect = flowVisibleRect(viewport, paneWidthPx, paneHeightPx, paddingPx);

  const visibleIds = new Set<string>();
  for (const n of nodes) {
    const { width: w, height: h } =
      n.width != null && n.height != null && n.width > 0 && n.height > 0
        ? { width: n.width, height: n.height }
        : getDefaultSize(n);
    const x = n.position.x;
    const y = n.position.y;
    if (rectsIntersect(x, y, w, h, rect)) {
      visibleIds.add(n.id);
    }
  }

  if (visibleIds.size === 0 && nodes.length > 0) {
    return { nodes, edges };
  }

  const prunedNodes = nodes.filter((n) => visibleIds.has(n.id));
  const prunedEdges = edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target));

  return { nodes: prunedNodes, edges: prunedEdges };
}
