/** Durable FP support pack for case timeline (Fraud Ops 4.2). */
export const FP_SUPPORT_PACK_LABEL = "fp_support_pack";

export function buildFpSupportPackPayload(input: {
  summaryMarkdown: string;
  actor: string;
}): { author: string; body: string; label: string } {
  const author = (input.actor || "").trim() || "analyst-web";
  const body = input.summaryMarkdown.trim();
  if (!body) {
    throw new Error("FP support pack summary is empty");
  }
  return { author, body, label: FP_SUPPORT_PACK_LABEL };
}
