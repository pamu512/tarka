/**
 * Recursively redacts secrets from arbitrary JSON-like structures before they are shown
 * or copied from the global error UI.
 */

const REDACTED = "[REDACTED]";

function keyLooksSensitive(key: string): boolean {
  const k = key.toLowerCase();
  if (k === "authorization" || k === "cookie" || k === "set-cookie") {
    return true;
  }
  if (k.includes("password")) {
    return true;
  }
  if (k.includes("secret")) {
    return true;
  }
  if (k.includes("apikey") || k.includes("api_key") || k === "x-api-key") {
    return true;
  }
  if (k === "access_token" || k === "refresh_token" || k === "id_token") {
    return true;
  }
  if (k.endsWith("token") || k.endsWith("_token")) {
    return true;
  }
  return false;
}

function looksLikeCompactJwt(value: string): boolean {
  const parts = value.split(".");
  return parts.length === 3 && parts.every((p) => p.length > 0) && value.length > 40;
}

function redactString(value: string): string {
  const t = value.trim();
  if (/^Bearer\s+\S+/i.test(t)) {
    return "[REDACTED Bearer credential]";
  }
  if (looksLikeCompactJwt(t)) {
    return "[REDACTED JWT]";
  }
  return value;
}

export function sanitizeErrorPayloadForDisplay(value: unknown): unknown {
  if (value === null || value === undefined) {
    return value;
  }
  if (typeof value === "string") {
    return redactString(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeErrorPayloadForDisplay(item));
  }
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
      if (keyLooksSensitive(key)) {
        out[key] = REDACTED;
        continue;
      }
      out[key] = sanitizeErrorPayloadForDisplay(raw);
    }
    return out;
  }
  return String(value);
}
