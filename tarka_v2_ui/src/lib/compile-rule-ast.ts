import type {
  ConditionNodeJson,
  LogicalNodeJson,
  Phase3Operator,
  TransactionSchemaField,
} from "@/types/rule-ast";

export const TRANSACTION_SCHEMA_FIELDS: readonly TransactionSchemaField[] = [
  "entity_id",
  "amount",
  "timestamp",
  "metadata",
  "country",
  "graph_linked_to_blocked_count",
] as const;

/** Human labels for the rule-builder field dropdown (wire keys stay ``TransactionSchema`` / extensions). */
export const TRANSACTION_FIELD_LABELS: Record<TransactionSchemaField, string> = {
  entity_id: "entity_id",
  amount: "amount",
  timestamp: "timestamp",
  metadata: "metadata",
  country: "country",
  graph_linked_to_blocked_count: "GRAPH_LINKED_TO_BLOCKED_COUNT (blocked users on same IP)",
};

export const PHASE3_OPERATORS: readonly Phase3Operator[] = [
  "EQ",
  "NE",
  "GT",
  "LT",
  "CONTAINS",
] as const;

export type ConditionBlock = {
  id: string;
  field: TransactionSchemaField;
  operator: Phase3Operator;
  valueRaw: string;
};

function stripOuterQuotes(s: string): string {
  const t = s.trim();
  if (
    (t.startsWith("'") && t.endsWith("'") && t.length >= 2) ||
    (t.startsWith('"') && t.endsWith('"') && t.length >= 2)
  ) {
    return t.slice(1, -1);
  }
  return t;
}

function parseValue(
  field: TransactionSchemaField,
  operator: Phase3Operator,
  raw: string,
): { ok: true; value: unknown } | { ok: false; message: string } {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { ok: false, message: "Value is required." };
  }

  if (operator === "GT" || operator === "LT") {
    const n = Number(trimmed);
    if (!Number.isFinite(n)) {
      return { ok: false, message: "GT and LT require a finite number." };
    }
    return { ok: true, value: n };
  }

  if (operator === "CONTAINS") {
    return { ok: true, value: stripOuterQuotes(trimmed) };
  }

  if (field === "amount") {
    const n = Number(trimmed);
    if (Number.isFinite(n)) {
      return { ok: true, value: n };
    }
    return { ok: false, message: "amount comparisons expect a numeric value." };
  }

  if (field === "metadata") {
    try {
      return { ok: true, value: JSON.parse(trimmed) as unknown };
    } catch {
      return { ok: false, message: "metadata value must be valid JSON." };
    }
  }

  return { ok: true, value: stripOuterQuotes(trimmed) };
}

function compileBlock(block: ConditionBlock): { ok: true; node: ConditionNodeJson } | { ok: false; message: string } {
  const rhs = parseValue(block.field, block.operator, block.valueRaw);
  if (!rhs.ok) {
    return { ok: false, message: rhs.message };
  }
  return {
    ok: true,
    node: {
      field: { field: block.field },
      operator: block.operator,
      value: rhs.value,
    },
  };
}

/**
 * Compile stacked condition blocks into a ``LogicalNode`` JSON object for the rule engine.
 * Multiple blocks are always combined with **AND** (``AndNode`` wire shape).
 */
export function compileBlocksToRootNode(
  blocks: ConditionBlock[],
): { ok: true; root: LogicalNodeJson } | { ok: false; message: string } {
  if (blocks.length === 0) {
    return { ok: false, message: "Add at least one condition block." };
  }

  const compiled: ConditionNodeJson[] = [];
  for (const b of blocks) {
    const one = compileBlock(b);
    if (!one.ok) {
      return { ok: false, message: one.message };
    }
    compiled.push(one.node);
  }

  if (compiled.length === 1) {
    return { ok: true, root: compiled[0] };
  }

  return { ok: true, root: { children: compiled } };
}

/** Canonical gate payload: ``amount > 500 AND country != 'US'``. */
export const GATE_RULE_BUILDER_BLOCKS: ConditionBlock[] = [
  {
    id: "gate-amount",
    field: "amount",
    operator: "GT",
    valueRaw: "500",
  },
  {
    id: "gate-country",
    field: "country",
    operator: "NE",
    valueRaw: "US",
  },
];

/** Example: ``amount > 100`` AND ``graph_linked_to_blocked_count > 0`` → graph-aware BLOCK. */
export const GRAPH_LINKED_BLOCKED_RULE_BLOCKS: ConditionBlock[] = [
  {
    id: "graph-ex-amount",
    field: "amount",
    operator: "GT",
    valueRaw: "100",
  },
  {
    id: "graph-ex-linked",
    field: "graph_linked_to_blocked_count",
    operator: "GT",
    valueRaw: "0",
  },
];

/** Single predicate ``amount > 1`` — use with Shadow Test to trigger the high-hit-rate warning gate. */
export const BROAD_RULE_SHADOW_TEST_BLOCKS: ConditionBlock[] = [
  {
    id: "broad-amount",
    field: "amount",
    operator: "GT",
    valueRaw: "1",
  },
];

export const GATE_RULE_BUILDER_JSON: LogicalNodeJson = {
  children: [
    {
      field: { field: "amount" },
      operator: "GT",
      value: 500,
    },
    {
      field: { field: "country" },
      operator: "NE",
      value: "US",
    },
  ],
};
