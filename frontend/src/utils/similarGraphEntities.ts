import type { RiskPropagationResult } from "../api/client";

/** Neighbors from graph-service ``risk-propagation`` (Gremlin BFS / JanusGraph), excluding the anchor vertex. */
export function normalizeSimilarEntities(
  anchorEntityId: string,
  entities: RiskPropagationResult[],
): RiskPropagationResult[] {
  const anchor = anchorEntityId.trim();
  return entities
    .filter((e) => e.entity_id !== anchor && e.distance > 0)
    .sort((a, b) => {
      const byScore = b.propagated_risk_score - a.propagated_risk_score;
      if (byScore !== 0) return byScore;
      return a.distance - b.distance;
    });
}
