import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { ForceGraphMethods, LinkObject, NodeObject } from "react-force-graph-2d";

import type { LinkAnalysisGraphNode } from "../domain/linkAnalysisGraph";

export type LinkAnalysisNodeSelectHandler = (entityId: string, node: LinkAnalysisGraphNode) => void;

export type LinkAnalysisForceLink = {
  source: string;
  target: string;
  relType: string;
};

function riskFill(score: number | null): string {
  if (score === null) return "rgba(107, 114, 128, 0.95)";
  if (score < 35) return "rgba(34, 197, 94, 0.95)";
  if (score < 65) return "rgba(234, 179, 8, 0.95)";
  if (score < 85) return "rgba(249, 115, 22, 0.95)";
  return "rgba(239, 68, 68, 0.95)";
}

export type LinkAnalysisForceGraphProps = {
  graphData: { nodes: LinkAnalysisGraphNode[]; links: LinkAnalysisForceLink[] };
  /** When true, reduce simulation work for very large pruned graphs. */
  largeGraph?: boolean;
  onNodeClick?: LinkAnalysisNodeSelectHandler;
};

export function LinkAnalysisForceGraph({ graphData, largeGraph, onNodeClick }: LinkAnalysisForceGraphProps) {
  const fgRef = useRef<ForceGraphMethods<LinkAnalysisGraphNode, LinkAnalysisForceLink> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 800, height: 560 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const read = () => {
      const r = el.getBoundingClientRect();
      setDims({
        width: Math.max(320, Math.floor(r.width)),
        height: Math.max(380, Math.floor(r.height)),
      });
    };
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (graphData.nodes.length === 0) return;
    const t = window.setTimeout(() => {
      fgRef.current?.zoomToFit?.(400, 40);
    }, 50);
    return () => window.clearTimeout(t);
  }, [graphData]);

  const nodeCanvasObject = useCallback(
    (node: LinkAnalysisGraphNode & { x?: number; y?: number }, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const g = globalScale || 1;
      const r = Math.max(4, 6 / g);
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI, false);
      ctx.fillStyle = riskFill(node.displayRisk);
      ctx.fill();
      ctx.strokeStyle = "rgba(15, 23, 42, 0.85)";
      ctx.lineWidth = 1 / g;
      ctx.stroke();

      const label = node.id.length > 14 ? `${node.id.slice(0, 12)}…` : node.id;
      const riskLabel = node.displayRisk === null ? "—" : `${node.displayRisk.toFixed(0)}`;
      const fontPx = Math.max(3, 10 / g);
      ctx.font = `${fontPx}px ui-sans-serif, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = "rgba(226, 232, 240, 0.95)";
      ctx.fillText(label, x, y + r + 1 / g);
      ctx.fillStyle = "rgba(251, 191, 36, 0.95)";
      ctx.font = `bold ${fontPx}px ui-monospace, monospace`;
      ctx.fillText(riskLabel, x, y + r + fontPx + 2 / g);
    },
    [],
  );

  const nodePointerAreaPaint = useCallback(
    (node: LinkAnalysisGraphNode & { x?: number; y?: number }, color: string, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const g = globalScale || 1;
      const r = Math.max(8, 14 / g);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI, false);
      ctx.fill();
    },
    [],
  );

  const linkColor = useCallback(() => "rgba(148, 163, 184, 0.35)", []);

  const simTuning = useMemo(() => {
    if (largeGraph) {
      return { d3VelocityDecay: 0.35, d3AlphaDecay: 0.05, cooldownTicks: 120, warmupTicks: 40 } as const;
    }
    return {} as const;
  }, [largeGraph]);

  return (
    <div
      ref={containerRef}
      className="w-full min-h-[380px] h-[min(70vh,720px)] rounded-lg border border-surface-800 bg-surface-950 overflow-hidden"
    >
      <ForceGraph2D
        ref={fgRef}
        width={dims.width}
        height={dims.height}
        graphData={graphData}
        backgroundColor="rgb(2 6 23)"
        nodeId="id"
        linkSource="source"
        linkTarget="target"
        linkColor={linkColor}
        linkWidth={0.6}
        linkDirectionalArrowLength={0}
        enableNodeDrag
        enableZoomInteraction
        enablePanInteraction
        minZoom={0.02}
        maxZoom={16}
        nodeCanvasObjectMode={() => "replace"}
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={nodePointerAreaPaint}
        linkLabel={(l: LinkObject<LinkAnalysisGraphNode, LinkAnalysisForceLink>) => {
          if (!l || typeof l !== "object") return "";
          return String((l as LinkAnalysisForceLink).relType ?? "");
        }}
        nodeLabel={(n: NodeObject<LinkAnalysisGraphNode>) => {
          const risk = n.displayRisk === null ? "risk n/a" : `risk ${n.displayRisk.toFixed(1)}`;
          return `${n.id} · ${risk}`;
        }}
        {...simTuning}
        onNodeClick={
          onNodeClick
            ? (node) => {
                const id = typeof node.id === "string" || typeof node.id === "number" ? String(node.id) : "";
                if (id) onNodeClick(id, node as LinkAnalysisGraphNode);
              }
            : undefined
        }
      />
    </div>
  );
}
