import { ruleForProductionDeploy } from "./promotionImpact";

export type PromoteHypothesisResponse = {
  version?: number;
  rule_count?: number;
  promotion_feedback?: Array<{
    ok?: boolean;
    nats_subject?: string | null;
    rule_id?: string;
    entity_count?: number;
    entity_ids?: string[];
  }>;
};

export async function fetchPromoteHypothesisToProduction(
  rule: Record<string, unknown>,
): Promise<PromoteHypothesisResponse> {
  const productionRule = ruleForProductionDeploy(rule);
  const res = await fetch("/api/v1/hypotheses/promote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rule: productionRule }),
  });
  const body = (await res.json().catch(() => ({}))) as PromoteHypothesisResponse & {
    error?: string;
    detail?: string;
  };
  if (!res.ok) {
    const msg =
      typeof body.error === "string"
        ? body.detail
          ? `${body.error}: ${body.detail}`
          : body.error
        : `Promote failed (${res.status})`;
    throw new Error(msg);
  }
  return body;
}
