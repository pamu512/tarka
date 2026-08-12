/**
 * Consent-gated first-party (CNAME-friendly) device context helpers.
 * Merged from former `@tarka/web-sdk` — prefer `@tarka/sdk` for all browser clients.
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
  // Fail-closed: no invented typing/motion signals until privacy-reviewed sampler ships.
  return {};
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

export async function publishDeviceContext(
  opts: TarkaSdkOptions,
  context: Record<string, unknown>,
): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.apiKey) headers["X-Api-Key"] = opts.apiKey;
  return fetch(opts.publishUrl, {
    method: "POST",
    headers,
    body: JSON.stringify({ device_context: context }),
    keepalive: true,
  });
}
