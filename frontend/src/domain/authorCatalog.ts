export type AuthorCatalogRedis = {
  name: string;
  kind: string;
  window?: string;
  window_seconds: number;
  field?: string;
};

export type AuthorCatalogGrowth = {
  name: string;
  kind: "growth";
  window: string;
  threshold: number;
};

export type AuthorCatalog = {
  redis: AuthorCatalogRedis[];
  growth: AuthorCatalogGrowth[];
  hops: Array<{ etype: string }>;
  payload: Array<{ name: string }>;
};

export const CATALOG_HOPS = ["USES_DEVICE", "HAS_EMAIL", "HAS_PHONE", "HAS_CARD", "HAS_LIST"] as const;

export function catalogFieldNames(c: AuthorCatalog): Set<string> {
  const names = new Set<string>();
  for (const row of c.redis) names.add(row.name);
  for (const row of c.growth) names.add(row.name);
  for (const row of c.payload) names.add(row.name);
  return names;
}

const REDIS_KIND_GROUPS: { kind: string; label: string }[] = [
  { kind: "event_count", label: "Count" },
  { kind: "sum", label: "Sum" },
  { kind: "avg", label: "Average" },
  { kind: "distinct", label: "Distinct" },
];

export function featurePickerGroups(
  catalog: AuthorCatalog,
): { label: string; options: { name: string; window?: string }[] }[] {
  const groups = REDIS_KIND_GROUPS.map(({ kind, label }) => ({
    label,
    options: catalog.redis.filter((r) => r.kind === kind).map((r) => ({ name: r.name, window: r.window })),
  })).filter((g) => g.options.length > 0);
  if (catalog.growth.length > 0) {
    groups.push({
      label: "Growth",
      options: catalog.growth.map((g) => ({ name: g.name, window: g.window })),
    });
  }
  return groups;
}

export function rulesPickerGroups(catalog: AuthorCatalog): { category: string; fields: string[] }[] {
  const groups = [
    { category: "Redis", fields: catalog.redis.map((r) => r.name) },
    { category: "Payload", fields: catalog.payload.map((p) => p.name) },
  ];
  if (catalog.growth.length > 0) {
    groups.push({ category: "Growth", fields: catalog.growth.map((g) => g.name) });
  }
  return groups.filter((g) => g.fields.length > 0);
}
