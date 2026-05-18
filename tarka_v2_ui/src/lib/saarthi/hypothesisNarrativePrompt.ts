/**
 * Saarthi hypothesis narrative (Prompt 195) — two-sentence Scout burst summary via Gemini.
 */

export const SAARTHI_HYPOTHESIS_NARRATIVE_SYSTEM = `You are Saarthi, a senior fraud analyst assistant. Given JSON from a DuckDB Scout coordinated-burst probe, write exactly two sentences for human analysts.

Sentence 1: Describe the coordination threat (e.g. potential botnet, device farm, spoofed iPhone/Android fingerprint) using only evidence in the JSON.

Sentence 2: State concrete scale and timing (distinct account count and elapsed hours between window_start_utc and window_end_utc).

Rules: plain English only; no markdown; no bullet characters; exactly two sentences; each sentence must end with a period; do not invent counts or times not present in the JSON.`;

export function buildHypothesisNarrativeUserContent(scoutJson: string): string {
  return `DuckDB Scout burst evidence (JSON):
${scoutJson}

Respond with exactly two sentences. Plain English only. No JSON, no markdown.`;
}

/** Gate / fallback when Gemini is unavailable — mirrors Python deterministic template. */
export function fallbackHypothesisNarrative(report: {
  fingerprint_kind?: string;
  fingerprint_value?: string;
  distinct_account_count?: number;
  window_hours_elapsed?: number;
}): string {
  const kind = report.fingerprint_kind ?? "canvas_hash";
  const fp = (report.fingerprint_value ?? "").toLowerCase();
  const count = report.distinct_account_count ?? 0;
  const hours = Math.max(1, Math.round(report.window_hours_elapsed ?? 2));
  const hourLabel = hours === 1 ? "1 hour" : `${hours} hours`;

  let sentenceOne: string;
  if (kind === "webgl_vendor") {
    sentenceOne = `A coordinated abuse cluster is reusing the same WebGL vendor string (${report.fingerprint_value ?? "unknown"}).`;
  } else if (fp.includes("iphone") || fp.includes("ios")) {
    sentenceOne = "A potential botnet is using a spoofed iPhone fingerprint.";
  } else if (fp.includes("android")) {
    sentenceOne = "A potential botnet is using a spoofed Android device fingerprint.";
  } else {
    sentenceOne = "A potential botnet is using a shared spoofed device canvas fingerprint.";
  }

  const accountWord = count === 1 ? "account" : "accounts";
  const sentenceTwo = `${count} ${accountWord} created in ${hourLabel}.`;
  return `${sentenceOne} ${sentenceTwo}`;
}

export function normalizeTwoSentenceNarrative(text: string): string | null {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (!cleaned) return null;
  const parts = cleaned.split(/(?<=[.!?])\s+/).filter((p) => p.trim().length > 0);
  if (parts.length !== 2) return null;
  const normalized = parts.map((p) => {
    const t = p.trim();
    return /[.!?]$/.test(t) ? t : `${t}.`;
  });
  return normalized.join(" ");
}
