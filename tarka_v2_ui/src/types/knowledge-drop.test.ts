import { describe, expect, it } from "vitest";
import {
  normalizeDuckClusterVelocity,
  normalizeKnowledgeRows,
  normalizeTwoHopNetwork,
} from "@/types/knowledge-drop";

describe("normalizeTwoHopNetwork", () => {
  it("parses graph neighborhood fields", () => {
    const row = normalizeTwoHopNetwork({
      found: true,
      anchor_user_id: "u-1",
      backend: "janusgraph",
      neighbor_node_count: 5,
      blocked_device_touch_count: 2,
      network_user_ids: ["u-1", "u-2"],
      network_device_ids: ["d-1"],
      network_ip_addresses: ["1.2.3.4", "5.6.7.8"],
      network_transaction_ids: ["t-1"],
      edges_summary: [{ from: "u-1", to: "d-1", rel: "USES" }],
    });
    expect(row?.found).toBe(true);
    expect(row?.network_user_ids).toEqual(["u-1", "u-2"]);
    expect(row?.edges_summary).toEqual(["u-1 → d-1 (USES)"]);
    expect(row?.blocked_device_touch_count).toBe(2);
  });

  it("surfaces backend errors", () => {
    const row = normalizeTwoHopNetwork({ error: "graph unavailable" });
    expect(row?.error).toBe("graph unavailable");
    expect(row?.found).toBe(false);
  });
});

describe("normalizeDuckClusterVelocity", () => {
  it("parses spike and spend metrics", () => {
    const row = normalizeDuckClusterVelocity({
      window_days: 30,
      total_spend_window: 1200,
      txn_count_window: 14,
      spend_last_2h: 400,
      spend_excluding_last_2h: 800,
      spike_pct_vs_flat_baseline_2h: 150,
      minute_velocity_last_48h: [{ minute_bucket: "2026-05-24T12:00:00Z", spend: 99 }],
    });
    expect(row?.spike_pct_vs_flat_baseline_2h).toBe(150);
    expect(row?.spend_last_2h).toBe(400);
    expect(row?.minute_velocity_last_48h[0]?.spend).toBe(99);
  });
});

describe("normalizeKnowledgeRows", () => {
  it("embeds topology and velocity on resolution rows", () => {
    const rows = normalizeKnowledgeRows([
      {
        detected_id: "ord-1",
        id_kind: "order",
        found_in_graph: true,
        two_hop_network: { found: true, neighbor_node_count: 3, backend: "janusgraph" },
        duck_cluster_velocity: { spend_last_2h: 50, spike_pct_vs_flat_baseline_2h: 220 },
      },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.two_hop_network?.neighbor_node_count).toBe(3);
    expect(rows[0]?.duck_cluster_velocity?.spike_pct_vs_flat_baseline_2h).toBe(220);
  });
});
