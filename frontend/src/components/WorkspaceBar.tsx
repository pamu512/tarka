import { useTenantEnvironment } from "../context/TenantEnvironmentContext";
import { DataSourceBadge } from "./DataSourceBadge";

const PRESETS = ["demo", "acme", "staging"];

export function WorkspaceBar() {
  const { tenantId, setTenantId, environment, setEnvironment } = useTenantEnvironment();
  return (
    <div className="flex flex-wrap items-center gap-2 min-w-0 text-xs">
      <DataSourceBadge />
      <select
        value={environment}
        onChange={(e) => setEnvironment(e.target.value as "sandbox" | "production")}
        className="bg-surface-800 border border-surface-600 rounded-md px-1.5 py-0.5 text-gray-300 max-w-[150px]"
        aria-label="Workspace environment (display only)"
        title="Display only — does not switch live stacks"
      >
        <option value="sandbox">Sandbox (display only)</option>
        <option value="production">Production (display only)</option>
      </select>
      <label className="flex items-center gap-1 min-w-0 text-gray-500">
        <span className="hidden lg:inline shrink-0">Tenant</span>
        <input
          list="tarka-tenant-dl"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          className="w-20 lg:w-28 bg-surface-800 border border-surface-600 rounded-md px-2 py-0.5 text-gray-200 font-mono text-[11px]"
          aria-label="Workspace tenant id"
        />
        <datalist id="tarka-tenant-dl">
          {PRESETS.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
      </label>
    </div>
  );
}
