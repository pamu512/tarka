import type { AuthorCatalog } from "../domain/authorCatalog";

const SKIP_HOP_RAW = new Set(["graph:missing", "graph:unavailable", "graph:empty"]);

function hopSet(catalog: AuthorCatalog): Set<string> {
  return new Set(catalog.hops.map((h) => h.etype));
}

function velocityNames(catalog: AuthorCatalog): Set<string> {
  const names = new Set<string>();
  for (const row of catalog.redis) names.add(row.name);
  for (const row of catalog.growth) names.add(row.name);
  return names;
}

function tokens(...raw: Array<string | null | undefined>): string[] {
  const out: string[] = [];
  for (const value of raw) {
    if (value == null) continue;
    const trimmed = value.trim();
    if (!trimmed) continue;
    out.push(trimmed);
  }
  return out;
}

export function parseHopEtype(catalog: AuthorCatalog, ...raw: Array<string | null | undefined>): string | null {
  const allowed = hopSet(catalog);
  for (const value of tokens(...raw)) {
    if (SKIP_HOP_RAW.has(value)) continue;
    const etype = value.startsWith("has_etype:") ? value.slice("has_etype:".length) : value;
    if (allowed.has(etype)) return etype;
  }
  return null;
}

export function parseVelocityField(catalog: AuthorCatalog, ...raw: Array<string | null | undefined>): string | null {
  const allowed = velocityNames(catalog);
  for (const value of tokens(...raw)) {
    if (allowed.has(value)) return value;
  }
  return null;
}

export function leftoverHuntSearch(row: {
  case_id: string;
  entity_id: string;
  tenant_id?: string;
  trace_id?: string;
  pack_id?: string;
  rule_hits?: string[];
}): URLSearchParams {
  const q = new URLSearchParams({
    entity_id: row.entity_id,
    leftover_id: row.case_id,
  });
  if (row.tenant_id) q.set("tenant_id", row.tenant_id);
  if (row.trace_id) q.set("decision_id", `dec:${row.trace_id}`);
  if (row.pack_id) q.set("pack", row.pack_id);
  if (row.rule_hits?.length) q.set("hits", row.rule_hits.join(","));
  return q;
}

export function leftoverVisualHref(
  catalog: AuthorCatalog,
  q: {
    leftoverId?: string | null;
    pack?: string | null;
    hits?: string | null;
    hopNamed?: string | null;
    entityId?: string | null;
    tenantId?: string | null;
    decisionId?: string | null;
  },
): string {
  const hitTokens = (q.hits ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const etype = parseHopEtype(catalog, q.hopNamed, ...hitTokens);
  const field = etype ? null : parseVelocityField(catalog, ...hitTokens, q.pack);
  const params = new URLSearchParams({ from: "leftover" });
  if (q.leftoverId) params.set("leftover_id", q.leftoverId);
  if (q.pack) params.set("pack", q.pack);
  if (q.hits) params.set("hits", q.hits);
  if (q.entityId) params.set("entity_id", q.entityId);
  if (q.tenantId) params.set("tenant_id", q.tenantId);
  if (q.decisionId) params.set("decision_id", q.decisionId);
  if (etype) params.set("etype", etype);
  if (field) params.set("field", field);
  return `/rules/visual?${params}`;
}
