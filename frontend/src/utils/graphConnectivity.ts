/**
 * Extract 1-hop neighbor **count** from graph-service `risk_factors` strings when explicit
 * `neighbors_1hop` is absent (Janus/Neo4j embed connectivity into factor labels).
 */
export function parseConnectivityNeighborCount(factors: string[] | undefined): number | null {
  if (!factors?.length) return null;
  for (const f of factors) {
    const high = /^high_connectivity:(\d+)$/.exec(f);
    const mod = /^moderate_connectivity:(\d+)$/.exec(f);
    if (high) return Number(high[1]);
    if (mod) return Number(mod[1]);
  }
  return null;
}
