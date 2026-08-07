import type { EntityRiskResult, InferenceContext } from "../api/client";
import type { TriageFlashCard } from "../components/CaseView/TriageHeader";

/** Scan-layer flash cards: Velocity, Graph, Geo (enrichment). */
export function buildTriageFlashCards(
  ctx: InferenceContext | null,
  graphRisk: EntityRiskResult | null,
): [TriageFlashCard, TriageFlashCard, TriageFlashCard] {
  const velocity: TriageFlashCard = !ctx
    ? { title: "Velocity", value: "—", tone: "neutral" }
    : ctx.velocity_events_24h >= 40
      ? { title: "Velocity", value: "High", tone: "critical" }
      : ctx.velocity_events_24h >= 12
        ? { title: "Velocity", value: "Elevated", tone: "warn" }
        : { title: "Velocity", value: "Normal", tone: "ok" };

  let graph: TriageFlashCard;
  if (!graphRisk) {
    graph = { title: "Graph", value: "—", tone: "neutral" };
  } else {
    const rs = graphRisk.risk_score;
    const factorHit = graphRisk.risk_factors?.find((f) => /mule|ring|sybil|farm/i.test(f)) ?? null;
    if (rs >= 0.65) {
      graph = {
        title: "Graph",
        value: factorHit ?? "Mule ring",
        tone: "critical",
      };
    } else if (rs >= 0.35) {
      graph = { title: "Graph", value: "Elevated", tone: "warn" };
    } else {
      graph = { title: "Graph", value: "Low linkage", tone: "ok" };
    }
  }

  const geo: TriageFlashCard = !ctx
    ? { title: "Geo (enrichment)", value: "—", tone: "neutral" }
    : ctx.impossible_travel_risk > 0.35 || ctx.geo_consistency_risk > 0.55
      ? { title: "Geo (enrichment)", value: "Inconsistent", tone: "critical" }
      : ctx.geo_consistency_risk > 0.22
        ? { title: "Geo (enrichment)", value: "Suspect", tone: "warn" }
        : { title: "Geo (enrichment)", value: "Consistent", tone: "ok" };

  return [velocity, graph, geo];
}
