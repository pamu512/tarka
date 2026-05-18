/**
 * Wire JSON aligned with :mod:`rule_engine.ast_schemas` (Prompt 16–19).
 *
 * ``AndNode`` / ``OrNode`` both serialize as ``{ children: [...] }``; the engine union
 * resolves grouped nodes to ``AndNode`` first for identical shapes — this UI compiles **AND** groups.
 */

export type TransactionSchemaField =
  | "entity_id"
  | "amount"
  | "timestamp"
  | "metadata"
  | "country"
  /** Graph constraint: blocked accounts sharing the subject user's IP (rule-engine hydrates via Neo4j). */
  | "graph_linked_to_blocked_count";

/** Phase-3 operator enum (``rule_engine.ast_schemas.Operator``). */
export type Phase3Operator = "EQ" | "NE" | "GT" | "LT" | "CONTAINS";

export type FieldRefJson = {
  field: TransactionSchemaField;
};

export type ConditionNodeJson = {
  field: FieldRefJson;
  operator: Phase3Operator;
  value: unknown;
};

export type GroupNodeJson = {
  children: Array<ConditionNodeJson | GroupNodeJson>;
};

export type LogicalNodeJson = ConditionNodeJson | GroupNodeJson;
