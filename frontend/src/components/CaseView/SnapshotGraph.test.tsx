import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseGraphSnapshot, SnapshotGraph } from "./SnapshotGraph";

describe("parseGraphSnapshot", () => {
  it("maps nodes and links to React Flow nodes/edges", () => {
    const { nodes, edges } = parseGraphSnapshot({
      nodes: [
        { id: "a", label: "A", kind: "user" },
        { id: "b", label: "B" },
      ],
      links: [{ source: "a", target: "b", rel: "knows" }],
    });
    expect(nodes).toHaveLength(2);
    expect(nodes[0].id).toBe("a");
    expect(nodes[0].data?.label).toBe("A");
    expect(edges).toHaveLength(1);
    expect(edges[0].source).toBe("a");
    expect(edges[0].target).toBe("b");
    expect(edges[0].label).toBe("knows");
  });

  it("accepts edges array as links", () => {
    const { edges } = parseGraphSnapshot({
      nodes: [{ id: "x" }, { id: "y" }],
      edges: [{ source: "x", target: "y" }],
    });
    expect(edges).toHaveLength(1);
  });

  it("drops links with unknown endpoints", () => {
    const { edges } = parseGraphSnapshot({
      nodes: [{ id: "a" }],
      links: [{ source: "a", target: "missing" }],
    });
    expect(edges).toHaveLength(0);
  });
});

describe("SnapshotGraph", () => {
  it("renders empty state when snapshot has no nodes", () => {
    render(<SnapshotGraph snapshot={{ nodes: [], links: [] }} />);
    expect(screen.getByTestId("case-snapshot-graph-empty")).toBeInTheDocument();
  });

  it("renders React Flow root when snapshot has nodes", () => {
    render(
      <SnapshotGraph
        snapshot={{
          nodes: [{ id: "n1", label: "One" }],
          links: [],
        }}
      />,
    );
    expect(screen.getByTestId("case-snapshot-graph-root")).toBeInTheDocument();
    expect(screen.getByText("One")).toBeInTheDocument();
  });
});
