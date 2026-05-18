import type { AstTranslatorPayload } from "./types";

const MAX_BADGES = 12;
const MAX_REASON_CHARS = 1200;
const MAX_BADGE_LEN = 40;

/**
 * Validate parsed JSON from Gemini into the AstTranslator contract.
 */
export function parseAstTranslatorPayload(raw: unknown): AstTranslatorPayload | null {
  if (raw == null || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const hr = o.humanReason;
  const bd = o.badges;
  if (typeof hr !== "string") return null;
  const trimmed = hr.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_REASON_CHARS) return null;
  if (!Array.isArray(bd)) return null;
  const badges: string[] = [];
  const seen = new Set<string>();
  for (const x of bd) {
    if (typeof x !== "string") continue;
    const b = x.trim();
    if (b.length === 0 || b.length > MAX_BADGE_LEN) continue;
    const key = b.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    badges.push(b);
    if (badges.length >= MAX_BADGES) break;
  }
  if (badges.length < 3) return null;
  return { humanReason: trimmed, badges };
}

/** Strip optional ```json fences from model output. */
export function extractJsonObject(text: string): string | null {
  const t = text.trim();
  const fence = /^```(?:json)?\s*([\s\S]*?)\s*```$/m.exec(t);
  if (fence) return fence[1]?.trim() ?? null;
  const start = t.indexOf("{");
  const end = t.lastIndexOf("}");
  if (start >= 0 && end > start) return t.slice(start, end + 1);
  return t.startsWith("{") ? t : null;
}

export function parseGeminiAstTranslatorText(text: string): AstTranslatorPayload | null {
  const slice = extractJsonObject(text);
  if (!slice) return null;
  try {
    const raw = JSON.parse(slice) as unknown;
    return parseAstTranslatorPayload(raw);
  } catch {
    return null;
  }
}
