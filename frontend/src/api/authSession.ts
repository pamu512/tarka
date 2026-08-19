/**
 * Desk session helpers. Access/refresh tokens live in httpOnly cookies
 * set by POST /api/auth/session. This module never writes tokens to
 * sessionStorage (or localStorage).
 *
 * An in-memory slot remains for unit tests / client-side RBAC probes.
 * Production SSO does not populate it — the browser cannot read httpOnly
 * cookies, and the SPA must send ``credentials: "include"`` instead.
 */

let memoryAccessToken: string | null = null;
let memoryRefreshToken: string | null = null;

export function getAccessToken(): string | null {
  return memoryAccessToken;
}

export function getRefreshToken(): string | null {
  return memoryRefreshToken;
}

export function setSessionTokens(accessToken: string, refreshToken: string | null): void {
  memoryAccessToken = accessToken && accessToken.trim() ? accessToken.trim() : null;
  if (refreshToken !== null) {
    memoryRefreshToken = refreshToken.trim() ? refreshToken.trim() : null;
  }
}

export function clearSessionTokens(): void {
  memoryAccessToken = null;
  memoryRefreshToken = null;
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
