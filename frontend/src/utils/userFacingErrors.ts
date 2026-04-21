type ErrorContext = {
  subject: string;
  action: string;
};

function extractStatusCode(message: string): number | null {
  const m = message.trim().match(/^(\d{3})\b/);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}

function withDebugTail(base: string, raw: string): string {
  const snippet = raw.trim().replace(/\s+/g, " ").slice(0, 140);
  if (!snippet) return base;
  return `${base} (${snippet})`;
}

export function toUserFacingError(error: unknown, context: ErrorContext): string {
  const raw = error instanceof Error ? error.message : String(error ?? "");
  const status = extractStatusCode(raw);

  if (status && status >= 500) {
    return withDebugTail(
      `${context.subject} is temporarily unavailable while we ${context.action}. Retry in a moment or switch to demo data if available.`,
      raw,
    );
  }
  if (status === 404) {
    return withDebugTail(
      `${context.subject} was not found for the current tenant or filter.`,
      raw,
    );
  }
  if (status === 401 || status === 403) {
    return withDebugTail(
      `You do not have permission to ${context.action}.`,
      raw,
    );
  }
  if (status === 400 || status === 422) {
    return withDebugTail(
      `Some input is invalid while trying to ${context.action}.`,
      raw,
    );
  }
  if (raw.toLowerCase().includes("failed to fetch")) {
    return `${context.subject} is unreachable from the browser right now. Check connectivity and service health, then retry.`;
  }

  return raw || `Unable to ${context.action}.`;
}
