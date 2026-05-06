type ErrorContext = {
  subject: string;
  action: string;
};

/** True when ``fetch`` was aborted (manual stop or ``AbortSignal.timeout``). */
export function isLikelyClientTimeoutOrAbort(error: unknown): boolean {
  if (error instanceof DOMException) {
    return error.name === "AbortError" || error.name === "TimeoutError";
  }
  if (error instanceof Error) {
    return error.name === "AbortError" || error.name === "TimeoutError";
  }
  return false;
}

function extractStatusCode(message: string): number | null {
  const m = message.trim().match(/^(\d{3})\b/);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}

export function extractSupportIdFromMessage(message: string): string | null {
  const m = message.match(/\b(?:support_id|support id|correlation_id|correlation id)\s*[:=]\s*([A-Za-z0-9._:-]{6,128})\b/i);
  if (!m) return null;
  return m[1];
}

function withSupportId(base: string, raw: string): string {
  const supportId = extractSupportIdFromMessage(raw);
  if (!supportId) return base;
  return `${base} Support ID: ${supportId}.`;
}

function withDebugTail(base: string, raw: string): string {
  if (/(?:support_id|support id|correlation_id|correlation id)\s*[:=]/i.test(raw)) return base;
  const snippet = raw.trim().replace(/\s+/g, " ").slice(0, 140);
  if (!snippet) return base;
  return `${base} (${snippet})`;
}

export function toUserFacingError(error: unknown, context: ErrorContext): string {
  const raw = error instanceof Error ? error.message : String(error ?? "");
  const status = extractStatusCode(raw);

  if (status && status >= 500) {
    return withDebugTail(withSupportId(
      `${context.subject} is temporarily unavailable while we ${context.action}. Retry in a moment or switch to demo data if available.`,
      raw,
    ), raw);
  }
  if (status === 404) {
    return withDebugTail(withSupportId(
      `${context.subject} was not found for the current tenant or filter.`,
      raw,
    ), raw);
  }
  if (status === 401 || status === 403) {
    return withDebugTail(withSupportId(
      `You do not have permission to ${context.action}.`,
      raw,
    ), raw);
  }
  if (status === 400 || status === 422) {
    return withDebugTail(withSupportId(
      `Some input is invalid while trying to ${context.action}.`,
      raw,
    ), raw);
  }
  if (raw.toLowerCase().includes("failed to fetch")) {
    return withSupportId(
      `${context.subject} is unreachable from the browser right now. Check connectivity and service health, then retry.`,
      raw,
    );
  }

  return withSupportId(raw || `Unable to ${context.action}.`, raw);
}
