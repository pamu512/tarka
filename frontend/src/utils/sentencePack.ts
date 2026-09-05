/** Fill-in-the-blank sentences → evaluate pack JSON. No invented keys or etypes. */

export const VELOCITY_KEYS = [
  "event_count_5m",
  "event_count_1h",
  "event_count_24h",
  "sum_amount_1h",
  "sum_amount_24h",
  "distinct_device_id_24h",
  "distinct_ip_address_24h",
] as const;

export const HOP_ETYPES = ["USES_DEVICE", "HAS_EMAIL", "HAS_PHONE", "HAS_CARD", "HAS_LIST"] as const;

export type VelocitySentence = {
  field: (typeof VELOCITY_KEYS)[number];
  op: "gte" | "gt" | "lte" | "lt";
  value: number;
};

export type HopSentence = {
  etype: (typeof HOP_ETYPES)[number];
};

export function emitVelocityPack(s: VelocitySentence): Record<string, unknown> {
  const field = VELOCITY_KEYS.includes(s.field) ? s.field : "event_count_1h";
  const n = Number.isFinite(s.value) ? s.value : 0;
  return {
    version: 1,
    name: `desk_${field}`,
    mode: "shadow",
    rules: [
      {
        id: `desk_${field}_${s.op}_${n}`,
        when: [{ field, op: s.op, value: n }],
        score_delta: 15,
        description: `When ${field} is ${s.op} ${n}`,
      },
    ],
  };
}

export function emitHopPack(s: HopSentence): Record<string, unknown> {
  const etype = HOP_ETYPES.includes(s.etype) ? s.etype : "USES_DEVICE";
  return {
    version: 1,
    name: `desk_hop_${etype.toLowerCase()}`,
    mode: "shadow",
    rules: [
      {
        id: `desk_hop_${etype.toLowerCase()}`,
        when_ast: { type: "graph_v1", atom: "has_etype", etype },
        score_delta: 18,
        tags: ["FLAG", `graph:has_etype:${etype}`],
        description: `FLAG when this person shares ${etype}`,
      },
    ],
  };
}
