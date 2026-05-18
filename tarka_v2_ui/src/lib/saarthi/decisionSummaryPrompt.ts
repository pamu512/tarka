/**
 * Saarthi "reasoning injection" for checkout-block narratives (Prompt 144).
 * Model: Gemini 1.5 Pro (default) — see decision-summary API route.
 */
export const SAARTHI_DECISION_SUMMARY_SYSTEM = `Translate this technical fraud block into a single sentence for a human analyst. Context: The user was blocked at checkout. Focus on the risk narrative (e.g., 'This device is linked to 4 previously blocked accounts').`;

export function buildDecisionSummaryUserContent(traceJson: string): string {
  return `execution_trace (JSON):
${traceJson}

Respond with exactly one sentence. Plain English only. No JSON, no markdown, no bullet characters.`;
}
