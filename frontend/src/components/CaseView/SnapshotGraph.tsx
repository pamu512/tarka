import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  ReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

/** One node in an evidence-locker ``graph_snapshot`` (orchestrator ``build_graph_viz`` shape). */
export type GraphSnapshotNode = {
  id: string;
  kind?: string;
  label?: string;
};

/** Link/edge: ``links`` (preferred) or ``edges`` array. */
export type GraphSnapshotLink = {
  source: string;
  target: string;
  rel?: string;
};

type SnapshotNodeData = { label: string; kind: string };
type SnapshotRfNode = Node<SnapshotNodeData, "snapshot">;

function SnapshotNodeCard({ data }: NodeProps<SnapshotRfNode>) {
  return (
    <div className="rounded-md border border-slate-500 bg-slate-900/95 px-2 py-1.5 text-xs text-slate-100 shadow-sm min-w-[72px] max-w-[168px]">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{data.kind}</div>
      <div className="font-medium truncate" title={data.label}>
        {data.label}
      </div>
    </div>
  );
}

const snapshotNodeTypes: NodeTypes = {
  snapshot: SnapshotNodeCard,
};

/**
 * Map persisted ``graph_snapshot`` JSON (nodes + links/edges) into React Flow elements.
 * Supports the orchestrator ``{ nodes: [{id, kind, label}], links: [{source, target, rel}] }`` shape.
 */
export function parseGraphSnapshot(snapshot: unknown): { nodes: SnapshotRfNode[]; edges: Edge[] } {
  if (snapshot == null || typeof snapshot !== "object") {
    return { nodes: [], edges: [] };
  }
  const o = snapshot as Record<string, unknown>;
  const rawNodes = Array.isArray(o.nodes) ? (o.nodes as GraphSnapshotNode[]) : [];
  const rawLinks: GraphSnapshotLink[] = Array.isArray(o.links)
    ? (o.links as GraphSnapshotLink[])
    : Array.isArray(o.edges)
      ? (o.edges as GraphSnapshotLink[])
      : [];

  const col = 200;
  const row = 110;
  const nodes: SnapshotRfNode[] = rawNodes.map((n, i) => ({
    id: String(n.id),
    type: "snapshot",
    position: { x: (i % 4) * col, y: Math.floor(i / 4) * row },
    data: {
      label: n.label != null && String(n.label).trim() !== "" ? String(n.label) : String(n.id),
      kind: n.kind != null && String(n.kind).trim() !== "" ? String(n.kind) : "Node",
    },
  }));

  const idSet = new Set(nodes.map((x) => x.id));
  const edges: Edge[] = [];
  rawLinks.forEach((e, i) => {
    const source = String(e.source);
    const target = String(e.target);
    if (!idSet.has(source) || !idSet.has(target)) return;
    edges.push({
      id: `snapshot-edge-${i}-${source}-${target}`,
      source,
      target,
      label: e.rel != null ? String(e.rel) : undefined,
    });
  });

  return { nodes, edges };
}

function SnapshotFlowInner({ nodes, edges }: { nodes: SnapshotRfNode[]; edges: Edge[] }) {
  return (
    <ReactFlow
      className="h-full w-full"
      nodes={nodes}
      edges={edges}
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
      proOptions={{ hideAttribution: true }}
    >
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
};

/**
 * Static React Flow view of a persisted graph snapshot (read-only nodes/edges).
 */
export function SnapshotGraph({ snapshot, height = 360, className }: SnapshotGraphProps) {
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

  const { nodes, edges } = useMemo(() => parseGraphSnapshot(parsed), [parsed]);

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
