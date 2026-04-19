/**
 * Browser vs server (and capability) detection for fail-open signal collection (#44).
 */

export type SdkRuntime = "browser" | "server" | "worker" | "unknown";

/** What this JS environment can use for device signal collection. */
export interface SdkCapabilityMatrix {
  runtime: SdkRuntime;
  /** `window` + `document` (typical browser tab). */
  is_browser: boolean;
  /** Web Crypto subtle (required for HMAC attestation + hashing). */
  has_subtle_crypto: boolean;
  /** `fetch` for API calls. */
  has_fetch: boolean;
  /** DOM for canvas / WebGL fingerprint helpers. */
  has_dom: boolean;
  /** `navigator` object. */
  has_navigator: boolean;
  /** `RTCPeerConnection` (VPN heuristic); often missing in lockdown / SSR. */
  has_rtc_peer_connection: boolean;
  /** `navigator.geolocation` (opt-in geo). */
  has_geolocation: boolean;
  /** `AudioContext` (audio fingerprint). */
  has_audio_context: boolean;
  /** `indexedDB` / storage APIs (may be blocked in private mode). */
  has_indexed_db_global: boolean;
}

export interface CollectorTimeoutsMs {
  /** WebRTC STUN / ICE heuristic. */
  vpn: number;
  /** ScriptProcessor audio pipeline. */
  audio: number;
  /** `navigator.geolocation.getCurrentPosition` (when enableGeo). */
  geo: number;
}

const DEFAULT_BROWSER: CollectorTimeoutsMs = {
  vpn: 2500,
  audio: 1200,
  geo: 2800,
};

const DEFAULT_SERVER: CollectorTimeoutsMs = {
  vpn: 0,
  audio: 0,
  geo: 0,
};

export function getSdkRuntime(): SdkRuntime {
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    return "browser";
  }
  if (typeof self !== "undefined" && typeof (self as any).importScripts === "function") {
    return "worker";
  }
  const proc = (globalThis as any).process;
  if (proc && proc.release?.name === "node") {
    return "server";
  }
  return "unknown";
}

export function describeSdkCapabilities(): SdkCapabilityMatrix {
  const runtime = getSdkRuntime();
  const is_browser = runtime === "browser";
  const has_dom = typeof document !== "undefined";
  const has_navigator = typeof navigator !== "undefined";
  const g = globalThis as any;
  const has_subtle_crypto =
    typeof crypto !== "undefined" && typeof crypto.subtle !== "undefined";
  const has_fetch = typeof fetch === "function";
  const has_rtc_peer_connection = typeof RTCPeerConnection !== "undefined";
  const has_geolocation = has_navigator && !!navigator.geolocation;
  const has_audio_context =
    typeof AudioContext !== "undefined" || typeof g.webkitAudioContext !== "undefined";
  const has_indexed_db_global = typeof indexedDB !== "undefined";

  return {
    runtime,
    is_browser,
    has_subtle_crypto,
    has_fetch,
    has_dom,
    has_navigator,
    has_rtc_peer_connection,
    has_geolocation,
    has_audio_context,
    has_indexed_db_global,
  };
}

/**
 * Per-collector timeouts: shorter in constrained environments; zero skips async collectors.
 */
export function resolveCollectorTimeouts(
  caps: SdkCapabilityMatrix,
  overrides?: Partial<CollectorTimeoutsMs>,
): CollectorTimeoutsMs {
  if (!caps.is_browser) {
    return { ...DEFAULT_SERVER, ...overrides };
  }
  const base = { ...DEFAULT_BROWSER };
  if (!caps.has_rtc_peer_connection) base.vpn = 0;
  if (!caps.has_audio_context) base.audio = 0;
  if (!caps.has_geolocation) base.geo = 0;
  return { ...base, ...overrides };
}

export interface FailOpenOptions {
  /** Label for optional `console.warn` on timeout/skip. */
  collectorName?: string;
  /** When true, log a one-line warning on timeout (browser only). */
  logTimeouts?: boolean;
}

/**
 * Race `promise` against `ms`; on timeout resolve `fallback` (fail-open for fraud UX).
 */
export async function withTimeoutFailOpen<T>(
  promise: Promise<T>,
  ms: number,
  fallback: T,
  opts?: FailOpenOptions,
): Promise<T> {
  if (ms <= 0) return fallback;
  return await new Promise<T>((resolve) => {
    const tid = setTimeout(() => {
      if (opts?.logTimeouts && typeof console !== "undefined" && console.warn) {
        const name = opts.collectorName ?? "collector";
        console.warn(`[tarka-sdk] ${name}: timeout after ${ms}ms; continuing fail-open`);
      }
      resolve(fallback);
    }, ms);
    promise
      .then((value) => {
        clearTimeout(tid);
        resolve(value);
      })
      .catch(() => {
        clearTimeout(tid);
        resolve(fallback);
      });
  });
}
