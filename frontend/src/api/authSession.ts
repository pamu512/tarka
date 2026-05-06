/**
 * Browser session token storage for bearer refresh flows.
 * Prefer httpOnly cookies at the edge in production; this module supports SPA-local tokens when required.
 */

const ACCESS_KEY = "tarka.session.access_token";
const REFRESH_KEY = "tarka.session.refresh_token";

function readKey(key: string): string | null {
  try {
    const v = sessionStorage.getItem(key);
    return v && v.trim() ? v.trim() : null;
  } catch {
    return null;
  }
}

function writeKey(key: string, value: string | null): void {
  try {
    if (value === null || value === "") {
      sessionStorage.removeItem(key);
    } else {
      sessionStorage.setItem(key, value);
    }
  } catch {
    /* storage may be unavailable — fail closed for callers that depend on persistence */
  }
}

export function getAccessToken(): string | null {
  return readKey(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return readKey(REFRESH_KEY);
}

export function setSessionTokens(accessToken: string, refreshToken: string | null): void {
  writeKey(ACCESS_KEY, accessToken);
  if (refreshToken !== null) {
    writeKey(REFRESH_KEY, refreshToken);
  }
}

export function clearSessionTokens(): void {
  writeKey(ACCESS_KEY, null);
  writeKey(REFRESH_KEY, null);
}

export const AUTH_SESSION_EXPIRED_EVENT = "tarka:auth-session-expired" as const;

export interface AuthSessionExpiredDetail {
  readonly reason: "refresh_failed" | "missing_tokens";
}

declare global {
  interface WindowEventMap {
    [AUTH_SESSION_EXPIRED_EVENT]: CustomEvent<AuthSessionExpiredDetail>;
  }
}

export function dispatchSessionExpired(reason: AuthSessionExpiredDetail["reason"]): void {
  clearSessionTokens();
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    const detail: AuthSessionExpiredDetail = { reason };
    window.dispatchEvent(new CustomEvent(AUTH_SESSION_EXPIRED_EVENT, { detail }));
  }
}
