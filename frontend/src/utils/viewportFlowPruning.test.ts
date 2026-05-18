import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";
import {
  flowVisibleRect,
  type NodeSizeDefaults,
  pruneNodesAndEdgesForViewport,
  VIEWPORT_PRUNE_PADDING_PX,
} from "./viewportFlowPruning";

const box: NodeSizeDefaults<Node> = () => ({ width: 100, height: 40 });

describe("flowVisibleRect", () => {
  it("maps pane corners into flow space", () => {
    const r = flowVisibleRect({ x: 0, y: 0, zoom: 1 }, 800, 600, 0);
    expect(r.minX).toBe(0);
    expect(r.maxX).toBe(800);
    expect(r.minY).toBe(0);
    expect(r.maxY).toBe(600);
  });

  it("expands rect by padding in flow units", () => {
    const r0 = flowVisibleRect({ x: 0, y: 0, zoom: 2 }, 800, 600, VIEWPORT_PRUNE_PADDING_PX);
    const padFlow = VIEWPORT_PRUNE_PADDING_PX / 2;
    expect(r0.minX).toBeCloseTo(0 - padFlow);
    expect(r0.maxX).toBeCloseTo(400 + padFlow);
  });
});

describe("pruneNodesAndEdgesForViewport", () => {
  it("keeps only nodes intersecting the viewport", () => {
    const nodes: Node[] = [
      { id: "a", position: { x: 0, y: 0 }, data: {}, width: 50, height: 50 },
      { id: "b", position: { x: 5000, y: 5000 }, data: {}, width: 50, height: 50 },
    ];
    const edges = [{ id: "e1", source: "a", target: "b" }];
    const out = pruneNodesAndEdgesForViewport(
      nodes,
      edges,
      { x: 0, y: 0, zoom: 1 },
      400,
      400,
      box,
      0,
    );
    expect(out.nodes.map((n) => n.id)).toEqual(["a"]);
    expect(out.edges).toHaveLength(0);
  });

  it("returns full graph when pane not measured", () => {
    const nodes: Node[] = [{ id: "a", position: { x: 0, y: 0 }, data: {} }];
    const out = pruneNodesAndEdgesForViewport(nodes, [], { x: 0, y: 0, zoom: 1 }, 0, 400, box);
    expect(out.nodes).toHaveLength(1);
  });

  it("falls back to full graph when nothing intersects", () => {
    const nodes: Node[] = [
      { id: "far", position: { x: 1e6, y: 1e6 }, data: {}, width: 10, height: 10 },
    ];
    const out = pruneNodesAndEdgesForViewport(nodes, [], { x: 0, y: 0, zoom: 1 }, 800, 600, box);
    expect(out.nodes).toHaveLength(1);
  });
});
