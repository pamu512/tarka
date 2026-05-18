import type { Connection, Edge, Node } from "@xyflow/react";

/** Directed adjacency from React Flow edges (source → target). */
function buildAdjacency(nodes: Node[], edges: Edge[]): Map<string, string[]> {
  const ids = new Set(nodes.map((n) => n.id));
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    const arr = adj.get(e.source);
    if (arr) arr.push(e.target);
    else adj.set(e.source, [e.target]);
  }
  return adj;
}

/**
 * If we add ``source → target``, would a directed cycle appear?
 * Equivalently: is there already a path ``target → … → source``?
 */
export function connectionCreatesDirectedCycle(nodes: Node[], edges: Edge[], conn: Connection): boolean {
  if (!conn.source || !conn.target) return false;
  const adj = buildAdjacency(nodes, edges);
  const goal = conn.source;
  const stack = [conn.target];
  const seen = new Set<string>();
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === goal) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const nxt of adj.get(cur) ?? []) stack.push(nxt);
  }
  return false;
}

const WHITE = 0;
const GREY = 1;
const BLACK = 2;

/** True if the current edge set contains any directed cycle (DFS coloring). */
export function graphHasDirectedCycle(nodes: Node[], edges: Edge[]): boolean {
  const adj = buildAdjacency(nodes, edges);
  const state = new Map<string, number>();

  const dfs = (u: string): boolean => {
    state.set(u, GREY);
    for (const v of adj.get(u) ?? []) {
      const s = state.get(v) ?? WHITE;
      if (s === GREY) return true;
      if (s === WHITE && dfs(v)) return true;
    }
    state.set(u, BLACK);
    return false;
  };

  for (const n of nodes) {
    if ((state.get(n.id) ?? WHITE) === WHITE && dfs(n.id)) return true;
  }
  return false;
}
