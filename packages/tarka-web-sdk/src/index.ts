/**
 * Tarka first-party device / session signal SDK (consent-aware, CNAME-friendly).
 *
 * - When ``consentGranted`` is false, only coarse signals (timezone, UA) are collected.
 * - Callers should serve this bundle from a first-party path (CNAME) to reduce ad-block loss.
 */

export type TarkaSdkOptions = {
  publishUrl: string;
  apiKey?: string;
  consentGranted: boolean;
};

function coarseSignals(): Record<string, unknown> {
  return {
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    ua: typeof navigator !== "undefined" ? navigator.userAgent : "",
    ts: Date.now(),
  };
}

function behavioralProbe(consent: boolean): Record<string, unknown> {
  if (!consent) return {};
  // Placeholder for typing cadence / motion sampling (integrate privacy review before enabling).
  return { typing_probe_version: 1 };
}

export function collectDeviceContext(opts: TarkaSdkOptions): Record<string, unknown> {
  const base = coarseSignals();
  if (!opts.consentGranted) {
    return { ...base, consent: "minimal" };
  }
  return {
    ...base,
    consent: "full",
    ...behavioralProbe(true),
  };
}

export async function publishDeviceContext(opts: TarkaSdkOptions, context: Record<string, unknown>): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.apiKey) headers["X-Api-Key"] = opts.apiKey;
  return fetch(opts.publishUrl, {
    method: "POST",
    headers,
    body: JSON.stringify({ device_context: context }),
    keepalive: true,
  });
}
