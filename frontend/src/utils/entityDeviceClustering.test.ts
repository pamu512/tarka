import { describe, expect, it } from "vitest";

import type { GraphEdge, GraphNode } from "../api/client";
import type { GraphSnapshotLink, GraphSnapshotNode } from "../components/CaseView/snapshotGraphTypes";
import {
  DEVICE_CLUSTER_GRAPH_LABEL,
  DEVICE_CLUSTER_ID_PREFIX,
  clusterSnapshotRaw,
  clusterSubgraphByDeviceHash,
  deviceHashFromGraphNode,
} from "./entityDeviceClustering";

describe("clusterSubgraphByDeviceHash", () => {
  it("merges vertices that share device_hash and dedupes parallel edges", () => {
    const nodes: GraphNode[] = [
      { id: "a", labels: ["User"], properties: { device_hash: "hx1" } },
      { id: "b", labels: ["User"], properties: { device_hash: "hx1" } },
      { id: "ip", labels: ["IP"], properties: {} },
    ];
    const edges: GraphEdge[] = [
      { from_id: "a", to_id: "ip", type: "FROM" },
      { from_id: "b", to_id: "ip", type: "FROM" },
    ];
    const out = clusterSubgraphByDeviceHash(nodes, edges);
    expect(out.nodes).toHaveLength(2);
    const cluster = out.nodes.find((n) => n.labels?.includes(DEVICE_CLUSTER_GRAPH_LABEL));
    expect(cluster?.id.startsWith(DEVICE_CLUSTER_ID_PREFIX)).toBe(true);
    expect(out.edges).toHaveLength(1);
    expect(out.edges[0]?.from_id).toBe(cluster?.id);
    expect(out.edges[0]?.to_id).toBe("ip");
  });

  it("does nothing when each hash is unique", () => {
    const nodes: GraphNode[] = [
      { id: "a", labels: ["User"], properties: { device_hash: "x" } },
      { id: "b", labels: ["User"], properties: { device_hash: "y" } },
    ];
    const edges: GraphEdge[] = [];
    const out = clusterSubgraphByDeviceHash(nodes, edges);
    expect(out.nodes).toHaveLength(2);
    expect(out.edges).toHaveLength(0);
  });
});

describe("clusterSnapshotRaw", () => {
  it("groups persisted snapshot nodes by device_hash", () => {
    const nodes: GraphSnapshotNode[] = [
      { id: "u1", kind: "User", device_hash: "snap1" },
      { id: "u2", kind: "User", device_hash: "snap1" },
      { id: "ip", kind: "IP" },
    ];
    const links: GraphSnapshotLink[] = [
      { source: "u1", target: "ip", rel: "FROM" },
      { source: "u2", target: "ip", rel: "FROM" },
    ];
    const out = clusterSnapshotRaw(nodes, links);
    expect(out.nodes.some((n) => n.kind === DEVICE_CLUSTER_GRAPH_LABEL)).toBe(true);
    expect(out.links).toHaveLength(1);
  });
});

describe("deviceHashFromGraphNode", () => {
  it("reads camelCase property", () => {
    const n: GraphNode = {
      id: "x",
      labels: [],
      properties: { deviceHash: "abc" },
    };
    expect(deviceHashFromGraphNode(n)).toBe("abc");
  });
});
