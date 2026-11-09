import type { AuthorCatalog } from "../../../domain/authorCatalog";

export type FieldValueType = "number" | "bool" | "enum" | "string" | "tag";

export type CatalogFieldDef = {
  name: string;
  valueType: FieldValueType;
  group: string;
  enumValues?: string[];
};

const BOOL_HINTS = /^(is_|has_|webdriver|headless|automation|ip_is_|timezone_)/i;
const NUMBER_KINDS = new Set(["event_count", "sum", "avg", "distinct"]);

/**
 * Map author-catalog entries to editor field defs.
 * Redis numeric kinds → number; payload bool-ish names → bool; else string.
 */
export function catalogToFields(catalog: AuthorCatalog): CatalogFieldDef[] {
  const out: CatalogFieldDef[] = [];

  for (const row of catalog.redis) {
    out.push({
      name: row.name,
      valueType: NUMBER_KINDS.has(row.kind) ? "number" : "string",
      group: "Redis",
    });
  }
  for (const row of catalog.growth) {
    out.push({ name: row.name, valueType: "number", group: "Growth" });
  }
  for (const row of catalog.payload) {
    out.push({
      name: row.name,
      valueType: BOOL_HINTS.test(row.name) ? "bool" : "string",
      group: "Payload",
    });
  }
  for (const row of catalog.computed ?? []) {
    out.push({ name: row.name, valueType: "number", group: "Computed" });
  }

  return out;
}
