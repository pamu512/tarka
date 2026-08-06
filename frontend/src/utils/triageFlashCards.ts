import type { EntityRiskResult, InferenceContext } from "../api/client";
import type { TriageFlashCard } from "../components/CaseView/TriageHeader";

export type LoyaltyGateSlice = {
  eligible?: boolean | null;
  status?: string;
};

export type LoyaltyEconomicsGates = {
  status?: string;
  gates?: Record<string, LoyaltyGateSlice>;
};

/** Best-effort read of loyalty gates from audit envelope / nested payload_snapshot. */
export function extractLoyaltyEconomicsGates(
  evaluatePayload: Record<string, unknown> | null | undefined,
): LoyaltyEconomicsGates | null {
  if (!evaluatePayload || typeof evaluatePayload !== "object") return null;
  const direct = evaluatePayload.loyalty_economics_gates;
  if (direct && typeof direct === "object" && !Array.isArray(direct)) {
    return direct as LoyaltyEconomicsGates;
  }
  const snap = evaluatePayload.payload_snapshot;
  if (snap && typeof snap === "object" && !Array.isArray(snap)) {
    const nested = (snap as Record<string, unknown>).loyalty_economics_gates;
    if (nested && typeof nested === "object" && !Array.isArray(nested)) {
      return nested as LoyaltyEconomicsGates;
    }
  }
  return null;
}

export function buildLoyaltyFlashCard(gates: LoyaltyEconomicsGates | null): TriageFlashCard {
  if (!gates) {
    return { title: "Loyalty", value: "Feeds req.", tone: "neutral" };
  }
  const topStatus = String(gates.status ?? "").trim();
  if (topStatus === "feeds_missing" || topStatus === "config_missing") {
    return { title: "Loyalty", value: "Feeds req.", tone: "neutral" };
  }
  const gateList = gates.gates ? Object.values(gates.gates) : [];
  const okGates = gateList.filter((g) => g?.status === "ok");
  if (okGates.length === 0) {
    return { title: "Loyalty", value: "Feeds req.", tone: "neutral" };
  }
  if (okGates.some((g) => g.eligible === false)) {
    return { title: "Loyalty", value: "Restricted", tone: "warn" };
  }
  if (okGates.every((g) => g.eligible === true)) {
    return { title: "Loyalty", value: "Eligible", tone: "ok" };
  }
  return { title: "Loyalty", value: "Feeds req.", tone: "neutral" };
}

/** Scan-layer flash cards: Velocity, Graph, Loyalty, Geo (enrichment). */
export function buildTriageFlashCards(
  ctx: InferenceContext | null,
  graphRisk: EntityRiskResult | null,
  loyaltyGates: LoyaltyEconomicsGates | null = null,
): [TriageFlashCard, TriageFlashCard, TriageFlashCard, TriageFlashCard] {
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

  const loyalty = buildLoyaltyFlashCard(loyaltyGates);

  const geo: TriageFlashCard = !ctx
    ? { title: "Geo (enrichment)", value: "—", tone: "neutral" }
    : ctx.impossible_travel_risk > 0.35 || ctx.geo_consistency_risk > 0.55
      ? { title: "Geo (enrichment)", value: "Inconsistent", tone: "critical" }
      : ctx.geo_consistency_risk > 0.22
        ? { title: "Geo (enrichment)", value: "Suspect", tone: "warn" }
        : { title: "Geo (enrichment)", value: "Consistent", tone: "ok" };

  return [velocity, graph, loyalty, geo];
}
