/** Demo / local first-hour copy. No competitor desk names. */

import { Link } from "react-router";

import { useTenantEnvironment } from "../context/TenantEnvironmentContext";

export function showFirstHourHint(tenantId: string, opts?: { isDev?: boolean }): boolean {
  const isDev = opts?.isDev ?? import.meta.env.DEV;
  const tid = tenantId.trim().toLowerCase();
  return isDev || tid === "demo" || tid === "local";
}

export function FirstHourHint({ job, nextTo, nextLabel }: { job: string; nextTo: string; nextLabel: string }) {
  const { tenantId } = useTenantEnvironment();
  if (!showFirstHourHint(tenantId || "demo")) return null;
  return (
    <aside
      data-testid="first-hour-hint"
      className="rounded-md border border-surface-700 bg-surface-900/80 px-3 py-2 text-sm text-gray-300"
    >
      <p>{job}</p>
      <p className="mt-1 text-gray-400">
        Next:{" "}
        <Link to={nextTo} className="text-brand-300 hover:underline">
          {nextLabel}
        </Link>
      </p>
    </aside>
  );
}
