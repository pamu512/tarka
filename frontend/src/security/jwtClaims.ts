/**
 * Client-side JWT **payload** decoding for RBAC routing only.
 * Does not verify signatures; APIs must continue to enforce auth server-side.
 */

const ROLES_CLAIM_DEFAULT = "roles";

function rolesClaimName(): string {
  const raw = import.meta.env.VITE_OIDC_ROLES_CLAIM?.trim();
  return raw || ROLES_CLAIM_DEFAULT;
}

function base64UrlToUtf8(segment: string): string {
  const padLen = (4 - (segment.length % 4)) % 4;
  const padded = segment.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat(padLen);
  const bin = atob(padded);
  try {
    return decodeURIComponent(
      Array.from(bin, (c) => `%${`00${c.charCodeAt(0).toString(16)}`.slice(-2)}`).join(""),
    );
  } catch {
    return bin;
  }
}

/**
 * Parses a JWT string and returns the JSON payload object, or `null` if the token is malformed.
 */
export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) {
    return null;
  }
  const [, payloadSeg] = parts;
  if (!payloadSeg) {
    return null;
  }
  try {
    const json = base64UrlToUtf8(payloadSeg);
    const parsed: unknown = JSON.parse(json);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Reads role strings from decoded OIDC/JWT claims using the same claim name as the backend
 * (`OIDC_ROLES_CLAIM`, default `roles` in `services/shared/auth_rbac.py`).
 */
export function extractRolesFromClaims(claims: Record<string, unknown>): string[] {
  const key = rolesClaimName();
  const raw = claims[key];
  if (typeof raw === "string" && raw.trim()) {
    return [raw.trim()];
  }
  if (Array.isArray(raw)) {
    return raw.flatMap((r) => (typeof r === "string" && r.trim() ? [r.trim()] : []));
  }
  const legacy = claims.role;
  if (typeof legacy === "string" && legacy.trim()) {
    return [legacy.trim()];
  }
  return [];
}
