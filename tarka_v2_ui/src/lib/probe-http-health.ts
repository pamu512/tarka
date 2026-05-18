import type { HealthServiceSnapshot } from "@/types/health-full";

const DEFAULT_TIMEOUT_MS = 2500;

function normalizeOfflineMessage(
  status: number,
  statusText: string,
  bodySnippet: string | null,
): string {
  const base = `${status} ${statusText || "Error"}`.trim();
  if (!bodySnippet) return base;
  const trimmed = bodySnippet.replace(/\s+/g, " ").trim().slice(0, 240);
  return trimmed ? `${base}: ${trimmed}` : base;
}

/**
 * Probes an HTTP(S) health URL with a hard timeout. Used server-side by the mock orchestrator.
 */
export async function probeHttpHealth(
  url: string,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<HealthServiceSnapshot> {
  const started = performance.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(url, {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
      headers: { Accept: "application/json, text/plain;q=0.9, */*;q=0.8" },
    });
    const latency_ms = Math.round(performance.now() - started);

    if (!res.ok) {
      const bodySnippet = await res.text().catch(() => null);
      return {
        online: false,
        latency_ms,
        error_message: normalizeOfflineMessage(res.status, res.statusText, bodySnippet),
      };
    }

    return { online: true, latency_ms, error_message: null };
  } catch (err) {
    const latency_ms = Math.round(performance.now() - started);
    const message =
      err instanceof Error
        ? err.name === "AbortError"
          ? `504 Gateway Timeout: probe exceeded ${timeoutMs}ms`
          : err.message
        : "Unknown probe error";

    const isConn =
      /ECONNREFUSED|ENOTFOUND|fetch failed|network|Failed to fetch/i.test(message);
    const error_message = isConn
      ? `503 Service Unavailable: ${message}`
      : message;

    return {
      online: false,
      latency_ms: Number.isFinite(latency_ms) ? latency_ms : null,
      error_message,
    };
  } finally {
    clearTimeout(timer);
  }
}
