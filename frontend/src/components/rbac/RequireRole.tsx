import type { ReactElement, ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { getAccessToken } from "@/api/authSession";
import type { ForbiddenUnauthorizedState } from "@/pages/ForbiddenUnauthorized";
import { decodeJwtPayload, extractRolesFromClaims } from "@/security/jwtClaims";

const FORBIDDEN_PATH = "/403-unauthorized";

const RBAC_LOG_PREFIX = "[RBAC]";

export type RequireRoleMatchMode = "any" | "all";

export interface RequireRoleProps {
  /**
   * Role name(s) that must appear **verbatim** in the JWT `roles` claim (or legacy `role`),
   * matching backend `OIDC_ROLES_CLAIM` / `services/shared/auth_rbac.py`.
   */
  allow: string | readonly string[];
  matchMode?: RequireRoleMatchMode;
  children: ReactNode;
}

function normalizeAllow(allow: string | readonly string[]): readonly string[] {
  return typeof allow === "string" ? [allow] : allow;
}

function rolesSatisfy(
  userRoles: readonly string[],
  required: readonly string[],
  matchMode: RequireRoleMatchMode,
): boolean {
  if (required.length === 0) {
    return false;
  }
  if (matchMode === "all") {
    return required.every((r) => userRoles.includes(r));
  }
  return required.some((r) => userRoles.includes(r));
}

export function RequireRole({ allow, matchMode = "any", children }: RequireRoleProps): ReactElement {
  const location = useLocation();
  const required = normalizeAllow(allow);
  const attemptedPath = `${location.pathname}${location.search}`;

  const token = getAccessToken();
  if (!token) {
    const rolesFromJwt: string[] = [];
    console.warn(RBAC_LOG_PREFIX, "route access denied", {
      attemptedPath,
      requiredRoles: required,
      rolesFromJwt,
      reason: "no_access_token",
    } satisfies Record<string, unknown>);
    const state: ForbiddenUnauthorizedState = {
      attemptedPath,
      requiredRoles: required,
      rolesFromJwt,
      reason: "no_access_token",
    };
    return <Navigate to={FORBIDDEN_PATH} replace state={state} />;
  }

  const claims = decodeJwtPayload(token);
  if (!claims) {
    const rolesFromJwt: string[] = [];
    console.warn(RBAC_LOG_PREFIX, "route access denied", {
      attemptedPath,
      requiredRoles: required,
      rolesFromJwt,
      reason: "malformed_jwt",
    } satisfies Record<string, unknown>);
    const state: ForbiddenUnauthorizedState = {
      attemptedPath,
      requiredRoles: required,
      rolesFromJwt,
      reason: "malformed_jwt",
    };
    return <Navigate to={FORBIDDEN_PATH} replace state={state} />;
  }

  const rolesFromJwt = extractRolesFromClaims(claims);
  if (!rolesSatisfy(rolesFromJwt, required, matchMode)) {
    console.warn(RBAC_LOG_PREFIX, "route access denied", {
      attemptedPath,
      requiredRoles: required,
      rolesFromJwt,
      reason: "role_denied",
    } satisfies Record<string, unknown>);
    const state: ForbiddenUnauthorizedState = {
      attemptedPath,
      requiredRoles: required,
      rolesFromJwt,
      reason: "role_denied",
    };
    return <Navigate to={FORBIDDEN_PATH} replace state={state} />;
  }

  return <>{children}</>;
}
