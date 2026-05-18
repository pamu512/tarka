/**
 * Fail-closed HTTP circuit: after repeated server failures, outbound requests are
 * short-circuited until cooldown elapses or {@link resetHttpCircuit} is called.
 */

export const TARKA_HTTP_CIRCUIT_OPEN_EVENT = "tarka:http-circuit-open" as const;

export interface HttpCircuitOpenDetail {
  readonly reason: "http_5xx" | "manual";
  readonly status: number;
  readonly url: string;
  readonly method: string;
  readonly openUntil: number;
  readonly consecutiveFailures: number;
}

declare global {
  interface WindowEventMap {
    [TARKA_HTTP_CIRCUIT_OPEN_EVENT]: CustomEvent<HttpCircuitOpenDetail>;
  }
}

const DEFAULT_COOLDOWN_MS = 30_000;
const FAILURE_THRESHOLD = 1;

let consecutive5xx = 0;
let openUntil = 0;

function cooldownMs(): number {
  const raw = import.meta.env.VITE_HTTP_CIRCUIT_COOLDOWN_MS;
  const n = raw !== undefined && raw !== "" ? Number(raw) : Number.NaN;
  return Number.isFinite(n) && n > 0 ? n : DEFAULT_COOLDOWN_MS;
}

export function isHttpCircuitOpen(): boolean {
  if (Date.now() >= openUntil) {
    openUntil = 0;
    return false;
  }
  return openUntil > 0;
}

/** Monotonic deadline from `Date.now()` while the circuit is open (0 when closed). */
export function getHttpCircuitDeadline(): number {
  return isHttpCircuitOpen() ? openUntil : 0;
}

export function resetHttpCircuit(): void {
  openUntil = 0;
  consecutive5xx = 0;
}

export function recordHttp5xxResponse(meta: {
  status: number;
  url: string;
  method: string;
}): void {
  if (meta.status < 500 || meta.status > 599) {
    return;
  }
  consecutive5xx += 1;
  if (consecutive5xx < FAILURE_THRESHOLD) {
    return;
  }
  const until = Date.now() + cooldownMs();
  openUntil = until;
  const detail: HttpCircuitOpenDetail = {
    reason: "http_5xx",
    status: meta.status,
    url: meta.url,
    method: meta.method,
    openUntil: until,
    consecutiveFailures: consecutive5xx,
  };
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent(TARKA_HTTP_CIRCUIT_OPEN_EVENT, { detail }));
  }
}

export function recordHttpSuccess(): void {
  consecutive5xx = 0;
}

export class HttpCircuitOpenError extends Error {
  readonly openUntil: number;

  constructor(openUntilTs: number) {
    super("HTTP circuit is open: outbound API calls are temporarily blocked.");
    this.name = "HttpCircuitOpenError";
    this.openUntil = openUntilTs;
  }
}

export function assertHttpCircuitClosed(): void {
  if (isHttpCircuitOpen()) {
    throw new HttpCircuitOpenError(openUntil);
  }
}
