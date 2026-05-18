import type { GraphEdge, GraphNode } from "../api/client";
import { pruneSubgraphForLinkView, type PruneSubgraphResult } from "./linkAnalysisGraph";

const WORKER_TIMEOUT_MS = 120_000;

/**
 * Prune a large subgraph. Uses a **web worker** when over the cap so the main thread
 * stays responsive; falls back to in-thread pruning if the worker fails to start.
 */
export async function pruneSubgraphAsync(
  nodes: GraphNode[],
  edges: GraphEdge[],
  seedEntityId: string,
  maxNodes: number,
): Promise<PruneSubgraphResult<GraphNode, GraphEdge>> {
  if (nodes.length <= maxNodes) {
    return pruneSubgraphForLinkView(nodes, edges, seedEntityId, maxNodes);
  }
  try {
    return await new Promise<PruneSubgraphResult<GraphNode, GraphEdge>>((resolve, reject) => {
      const worker = new Worker(new URL("../workers/linkAnalysisPrune.worker.ts", import.meta.url), {
        type: "module",
      });
      const timer = window.setTimeout(() => {
        worker.terminate();
        reject(new Error("link_analysis_prune_worker_timeout"));
      }, WORKER_TIMEOUT_MS);
      worker.onmessage = (e: MessageEvent<PruneSubgraphResult<GraphNode, GraphEdge>>) => {
        window.clearTimeout(timer);
        worker.terminate();
        resolve(e.data);
      };
      worker.onerror = (e) => {
        window.clearTimeout(timer);
        worker.terminate();
        reject(e.error ?? new Error(e.message));
      };
      worker.postMessage({ nodes, edges, seedEntityId, maxNodes });
    });
  } catch {
    return pruneSubgraphForLinkView(nodes, edges, seedEntityId, maxNodes);
  }
}
