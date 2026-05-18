/// <reference lib="webworker" />

import {
  pruneSubgraphForLinkView,
  type LinkPruneEdge,
  type LinkPruneNode,
  type PruneSubgraphResult,
} from "../domain/linkAnalysisGraph";

export type PruneWorkerInput = {
  nodes: LinkPruneNode[];
  edges: LinkPruneEdge[];
  seedEntityId: string;
  maxNodes: number;
};

addEventListener("message", (event: MessageEvent<PruneWorkerInput>) => {
  const { nodes, edges, seedEntityId, maxNodes } = event.data;
  const result: PruneSubgraphResult = pruneSubgraphForLinkView(nodes, edges, seedEntityId, maxNodes);
  postMessage(result);
});
