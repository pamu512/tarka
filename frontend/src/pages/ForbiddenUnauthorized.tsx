import type { ReactElement } from "react";
import { Link, useLocation } from "react-router-dom";

export type ForbiddenUnauthorizedState = {
  readonly attemptedPath: string;
  readonly requiredRoles: readonly string[];
  readonly rolesFromJwt: readonly string[];
  readonly reason: "no_access_token" | "malformed_jwt" | "role_denied";
};

function readState(location: ReturnType<typeof useLocation>): ForbiddenUnauthorizedState | null {
  const s = location.state;
  if (s && typeof s === "object" && "reason" in s && "attemptedPath" in s) {
    return s as ForbiddenUnauthorizedState;
  }
  return null;
}

export default function ForbiddenUnauthorized(): ReactElement {
  const location = useLocation();
  const detail = readState(location);

  return (
    <div className="mx-auto max-w-lg px-6 py-16 text-center space-y-4">
      <h1 className="text-2xl font-semibold text-gray-100">403 Unauthorized</h1>
      <p className="text-sm text-gray-400">
        You do not have permission to open this part of Tarka. If you believe this is a mistake,
        contact your organization administrator.
      </p>
      {detail ? (
        <dl className="rounded-lg border border-surface-700 bg-surface-900/80 text-left text-xs text-gray-400 space-y-2 p-4 font-mono">
          <div>
            <dt className="text-gray-500">Attempted path</dt>
            <dd className="text-gray-200 break-all">{detail.attemptedPath}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Required role(s)</dt>
            <dd className="text-gray-200">{detail.requiredRoles.join(", ") || "(none)"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Roles from JWT</dt>
            <dd className="text-gray-200">{detail.rolesFromJwt.length ? detail.rolesFromJwt.join(", ") : "(none)"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Reason</dt>
            <dd className="text-gray-200">{detail.reason}</dd>
          </div>
        </dl>
      ) : null}
      <div className="pt-4">
        <Link
          to="/dashboard"
          className="inline-flex items-center justify-center rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-500 transition-colors"
        >
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
