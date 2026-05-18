import { describe, expect, it } from "vitest";

import {
  MAX_VISIBLE_SPOKES_PER_SUPER,
  SUPER_NODE_DEGREE_THRESHOLD,
  buildAdjacency,
  partitionSuperNodeNeighbors,
  parseGraphSnapshot,
  pruneSuperNodeFans,
} from "./snapshotGraphLayout";

describe("super-node pruning", () => {
  it("detects hubs with degree above threshold", () => {
    const hub = "hub";
    const leaves = Array.from({ length: 20 }, (_, i) => `leaf-${i}`);
    const nodes = [{ id: hub, kind: "User", label: "Hub" }, ...leaves.map((id) => ({ id }))];
    const links = leaves.map((id) => ({ source: hub, target: id }));
    const adj = buildAdjacency(
      nodes.map((n) => String(n.id)),
      links,
    );
    expect((adj.get(hub)?.size ?? 0)).toBe(20);
    expect((adj.get(hub)?.size ?? 0) > SUPER_NODE_DEGREE_THRESHOLD).toBe(true);
  });

  it("collapses excess leaf neighbors into a bundle node", () => {
    const hub = "center";
    const leaves = Array.from({ length: 20 }, (_, i) => `L${i}`);
    const nodes = [{ id: hub }, ...leaves.map((id) => ({ id }))];
    const links = leaves.map((id) => ({ source: hub, target: id }));
    const pruned = pruneSuperNodeFans({ rawNodes: nodes, rawLinks: links });
    expect(pruned.bundleMeta.has(hub)).toBe(true);
    expect(pruned.bundleMeta.get(hub)?.bundledLeafIds.length).toBe(20 - MAX_VISIBLE_SPOKES_PER_SUPER);
    expect(pruned.nodesOut.some((n) => String(n.id).startsWith("snapshot-bundle:"))).toBe(true);
    const maxEdgesFromHub = MAX_VISIBLE_SPOKES_PER_SUPER + 1;
    const outFromHub = pruned.linksOut.filter(
      (e) => e.source === hub || e.target === hub,
    ).length;
    expect(outFromHub).toBeLessThanOrEqual(maxEdgesFromHub);
  });

  it("parseGraphSnapshot assigns snapshotBundle type for grouped chips", () => {
    const hub = "h";
    const leaves = Array.from({ length: 18 }, (_, i) => ({ id: `n${i}` }));
    const snapshot = {
      nodes: [{ id: hub }, ...leaves],
      links: leaves.map((n) => ({ source: hub, target: n.id })),
    };
    const { nodes } = parseGraphSnapshot(snapshot);
    expect(nodes.some((x) => x.type === "snapshotBundle")).toBe(true);
    expect(nodes.filter((x) => x.type === "snapshot")).toHaveLength(
      1 + MAX_VISIBLE_SPOKES_PER_SUPER,
    );
  });

  it("parseGraphSnapshot maps shared device_hash groups to snapshotDeviceCluster when enabled", () => {
    const snapshot = {
      nodes: [
        { id: "u1", kind: "User", device_hash: "dh_shared" },
        { id: "u2", kind: "User", device_hash: "dh_shared" },
        { id: "ip", kind: "IP" },
      ],
      links: [
        { source: "u1", target: "ip", rel: "FROM" },
        { source: "u2", target: "ip", rel: "FROM" },
      ],
    };
    const { nodes } = parseGraphSnapshot(snapshot, { clusterByDeviceHash: true });
    expect(nodes.some((x) => x.type === "snapshotDeviceCluster")).toBe(true);
    expect(nodes.filter((x) => x.type === "snapshot")).toHaveLength(1);
  });
});

describe("partitionSuperNodeNeighbors", () => {
  it("prioritizes structural neighbors before leaves when under cap", () => {
    const adj = new Map<string, Set<string>>([
      ["hub", new Set(["s1", "s2", ...Array.from({ length: 20 }, (_, i) => `L${i}`)])],
      ["s1", new Set(["hub", "other"])],
      ["s2", new Set(["hub", "other2"])],
      ["other", new Set(["s1"])],
      ["other2", new Set(["s2"])],
    ]);
    for (let i = 0; i < 20; i += 1) {
      const id = `L${i}`;
      adj.set(id, new Set(["hub"]));
    }
    const { visible, bundledLeaves, structuralOverflow } = partitionSuperNodeNeighbors(adj, "hub");
    expect(structuralOverflow.length).toBe(0);
    expect(visible).toContain("s1");
    expect(visible).toContain("s2");
    expect(visible.length).toBeLessThanOrEqual(MAX_VISIBLE_SPOKES_PER_SUPER);
    expect(bundledLeaves.length + visible.length).toBe(22);
  });
});
