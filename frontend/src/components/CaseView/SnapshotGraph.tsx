import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  type NodeProps,
  type NodeTypes,
  ReactFlow,
  ReactFlowProvider,
  useStore,
  useViewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { pruneNodesAndEdgesForViewport } from "../../utils/viewportFlowPruning";
import {
  type AnySnapshotRfNode,
  type SnapshotBundleData,
  type SnapshotDeviceClusterData,
  type SnapshotNodeData,
  parseGraphSnapshot,
  snapshotRfNodeDimensions,
} from "./snapshotGraphLayout";

export type { GraphSnapshotLink, GraphSnapshotNode } from "./snapshotGraphTypes";
export { parseGraphSnapshot };

type SnapshotRfNodeTyped = import("@xyflow/react").Node<SnapshotNodeData, "snapshot">;
type SnapshotBundleRfNodeTyped = import("@xyflow/react").Node<SnapshotBundleData, "snapshotBundle">;
type SnapshotDeviceClusterRfNodeTyped = import("@xyflow/react").Node<
  SnapshotDeviceClusterData,
  "snapshotDeviceCluster"
>;

function SnapshotNodeCard({ data }: NodeProps<SnapshotRfNodeTyped>) {
  return (
    <div className="rounded-md border border-slate-500 bg-slate-900/95 px-2 py-1.5 text-xs text-slate-100 shadow-sm min-w-[72px] max-w-[168px]">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{data.kind}</div>
      <div className="font-medium truncate" title={data.label}>
        {data.label}
      </div>
    </div>
  );
}

function SnapshotBundleCard({ data }: NodeProps<SnapshotBundleRfNodeTyped>) {
  const preview =
    data.bundledIdsPreview.length > 0
      ? data.bundledIdsPreview.slice(0, 8).join(", ") + (data.bundledIdsPreview.length >= 8 ? "…" : "")
      : "";
  return (
    <div
      className="rounded-md border border-amber-600/80 bg-amber-950/90 px-2 py-1.5 text-xs text-amber-100 shadow-sm min-w-[100px] max-w-[200px]"
      title={preview || data.label}
    >
      <div className="text-[10px] uppercase tracking-wide text-amber-400/90">Grouped</div>
      <div className="font-semibold leading-snug">{data.label}</div>
      {(data.bundledLeafCount > 0 || data.structuralOverflowCount > 0) && (
        <div className="mt-0.5 text-[10px] text-amber-200/70">
          {data.bundledLeafCount > 0 ? `${data.bundledLeafCount} leaf` : null}
          {data.bundledLeafCount > 0 && data.structuralOverflowCount > 0 ? " · " : null}
          {data.structuralOverflowCount > 0 ? `${data.structuralOverflowCount} linked` : null}
        </div>
      )}
    </div>
  );
}

function SnapshotDeviceClusterCard({ data }: NodeProps<SnapshotDeviceClusterRfNodeTyped>) {
  const preview =
    data.memberIdsPreview.length > 0
      ? data.memberIdsPreview.slice(0, 6).join(", ") + (data.memberIdsPreview.length > 6 ? "…" : "")
      : "";
  return (
    <div
      className="rounded-md border border-violet-500/70 bg-violet-950/90 px-2 py-1.5 text-xs text-violet-100 shadow-sm min-w-[100px] max-w-[200px]"
      title={preview || data.label}
    >
      <div className="text-[10px] uppercase tracking-wide text-violet-300/90">Shared device</div>
      <div className="font-semibold leading-snug">{data.label}</div>
      <div className="mt-0.5 text-[10px] font-mono text-violet-200/80 truncate" title={data.hashPreview}>
        {data.hashPreview}
      </div>
      {data.memberCount > 0 ? (
        <div className="mt-0.5 text-[10px] text-violet-200/70">{data.memberCount} vertices merged</div>
      ) : null}
    </div>
  );
}

const snapshotNodeTypes: NodeTypes = {
  snapshot: SnapshotNodeCard,
  snapshotBundle: SnapshotBundleCard,
  snapshotDeviceCluster: SnapshotDeviceClusterCard,
};

/** Above this node count, viewport pruning reduces rendered nodes/edges (Prompt 158). */
const VIEWPORT_PRUNE_MIN_NODES = 80;

function ViewportPruneSync({
  fullNodes,
  fullEdges,
  onPruned,
}: {
  fullNodes: AnySnapshotRfNode[];
  fullEdges: Edge[];
  onPruned: (next: { nodes: AnySnapshotRfNode[]; edges: Edge[] }) => void;
}) {
  const vp = useViewport();
  const width = useStore((s) => s.width);
  const height = useStore((s) => s.height);

  useLayoutEffect(() => {
    if (fullNodes.length < VIEWPORT_PRUNE_MIN_NODES || width < 32 || height < 32) {
      onPruned({ nodes: fullNodes, edges: fullEdges });
      return;
    }
    onPruned(
      pruneNodesAndEdgesForViewport(
        fullNodes,
        fullEdges,
        vp,
        width,
        height,
        snapshotRfNodeDimensions,
      ),
    );
  }, [fullNodes, fullEdges, vp, width, height, onPruned]);

  return null;
}

function SnapshotFlowInner({
  nodes: fullNodes,
  edges: fullEdges,
}: {
  nodes: AnySnapshotRfNode[];
  edges: Edge[];
}) {
  const [rendered, setRendered] = useState<{ nodes: AnySnapshotRfNode[]; edges: Edge[] }>(() => ({
    nodes: fullNodes,
    edges: fullEdges,
  }));

  useEffect(() => {
    setRendered({ nodes: fullNodes, edges: fullEdges });
  }, [fullNodes, fullEdges]);

  const onPruned = useCallback((next: { nodes: AnySnapshotRfNode[]; edges: Edge[] }) => {
    setRendered((prev) => {
      if (
        prev.nodes.length === next.nodes.length &&
        prev.edges.length === next.edges.length &&
        prev.nodes.every((n, i) => n.id === next.nodes[i]?.id) &&
        prev.edges.every((e, i) => e.id === next.edges[i]?.id)
      ) {
        return prev;
      }
      return next;
    });
  }, []);

  return (
    <ReactFlow
      className="h-full w-full"
      nodes={rendered.nodes}
      edges={rendered.edges}
      nodeTypes={snapshotNodeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      edgesReconnectable={false}
      zoomOnScroll
      panOnScroll={false}
      preventScrolling
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.25}
      maxZoom={1.5}
      onlyRenderVisibleElements
      proOptions={{ hideAttribution: true }}
    >
      <ViewportPruneSync fullNodes={fullNodes} fullEdges={fullEdges} onPruned={onPruned} />
      <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export type SnapshotGraphProps = {
  /** Raw ``cases.graph_snapshot`` / export bundle JSON (object or JSON string). */
  snapshot: unknown;
  height?: number;
  className?: string;
  /** Group snapshot vertices that share ``device_hash`` (botnet / farm visibility). */
  clusterByDeviceHash?: boolean;
};

/**
 * Static React Flow view of a persisted graph snapshot (read-only nodes/edges).
 * Super-nodes (degree &gt; 15) collapse excess fan-out via a **Grouped** bundle chip (Prompt 139).
 */
export function SnapshotGraph({
  snapshot,
  height = 360,
  className,
  clusterByDeviceHash = true,
}: SnapshotGraphProps) {
  const parsed = useMemo(() => {
    if (typeof snapshot === "string") {
      try {
        return JSON.parse(snapshot) as unknown;
      } catch {
        return null;
      }
    }
    return snapshot;
  }, [snapshot]);

  const { nodes, edges } = useMemo(
    () => parseGraphSnapshot(parsed, { clusterByDeviceHash }),
    [parsed, clusterByDeviceHash],
  );

  if (nodes.length === 0) {
    return (
      <div
        className={`flex items-center justify-center rounded-lg border border-surface-700 bg-surface-900/60 text-sm text-gray-500 ${className ?? ""}`}
        style={{ height }}
        data-testid="case-snapshot-graph-empty"
      >
        No graph snapshot nodes to display.
      </div>
    );
  }

  return (
    <div
      className={`rounded-xl border border-surface-700 bg-surface-950 overflow-hidden ${className ?? ""}`}
      style={{ height }}
      data-testid="case-snapshot-graph-root"
    >
      <ReactFlowProvider>
        <div className="h-full w-full">
          <SnapshotFlowInner nodes={nodes} edges={edges} />
        </div>
      </ReactFlowProvider>
    </div>
  );
}
