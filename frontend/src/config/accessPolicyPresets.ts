/**
 * Organizational access policies (role templates) for RBAC.
 * Distinct from ACCESS_GROUPS in accessModuleCatalog.ts (those are UI groupings of modules).
 */
import { allAccessModuleIds, type AccessModuleId } from "./accessModuleCatalog";

export type AccessPolicyId =
  | "platform_admin"
  | "engineering"
  | "data_science"
  | "risk_analyst"
  | "view_only"
  | "governance";

export type AccessPolicyPreset = {
  id: AccessPolicyId;
  label: string;
  shortLabel: string;
  description: string;
  /** May grant/revoke module access for other users (enforce in admin-api / IdP). */
  canManageAccess: boolean;
  moduleIds: AccessModuleId[];
};

const ALL = allAccessModuleIds();

export const ACCESS_POLICY_PRESETS: AccessPolicyPreset[] = [
  {
    id: "platform_admin",
    label: "Platform administrator",
    shortLabel: "Admin",
    description:
      "Full product modules plus authority to add or remove access for others. Changes to core or high-risk modules still go through dual approval when configured.",
    canManageAccess: true,
    moduleIds: [...ALL],
  },
  {
    id: "engineering",
    label: "Engineering",
    shortLabel: "Engineering",
    description:
      "Build and operate fraud systems: rules, simulation, shadow, integrations, graph, and investigation tools. Excludes the Admin Panel (no RBAC management).",
    canManageAccess: false,
    moduleIds: [
      "dashboard",
      "cases",
      "disputes",
      "graph",
      "investigation",
      "osint",
      "analytics",
      "rules",
      "entity-lists",
      "shadow",
      "simulation",
      "compliance",
      "integrations",
      "notifications",
      "settings",
    ],
  },
  {
    id: "data_science",
    label: "Data science",
    shortLabel: "Data science",
    description:
      "Modeling and experimentation: analytics, simulation, investigation copilot, lists, and case/dispute data for labels — without admin or production integration changes.",
    canManageAccess: false,
    moduleIds: [
      "dashboard",
      "cases",
      "disputes",
      "investigation",
      "analytics",
      "rules",
      "entity-lists",
      "shadow",
      "simulation",
      "notifications",
      "settings",
    ],
  },
  {
    id: "risk_analyst",
    label: "Risk analyst",
    shortLabel: "Risk analyst",
    description:
      "Day-to-day fraud operations: queues, graph, OSINT, rules read/write, lists, shadow — full investigation surface without engineering integrations plane or admin.",
    canManageAccess: false,
    moduleIds: [
      "dashboard",
      "cases",
      "disputes",
      "graph",
      "investigation",
      "osint",
      "analytics",
      "rules",
      "entity-lists",
      "shadow",
      "simulation",
      "compliance",
      "notifications",
      "settings",
    ],
  },
  {
    id: "view_only",
    label: "View only",
    shortLabel: "View only",
    description:
      "Read dashboards and personal account areas only — no case actions, rules, graph, or sensitive tooling.",
    canManageAccess: false,
    moduleIds: ["dashboard", "notifications", "settings"],
  },
  {
    id: "governance",
    label: "Governance & audit",
    shortLabel: "Governance",
    description:
      "Compliance, integrations oversight, admin console, and read access to operational modules for audits — typically paired with maker–checker on changes.",
    canManageAccess: true,
    moduleIds: [
      "dashboard",
      "cases",
      "disputes",
      "analytics",
      "compliance",
      "integrations",
      "notifications",
      "settings",
      "admin",
    ],
  },
];

export function getAccessPolicyPreset(id: AccessPolicyId): AccessPolicyPreset | undefined {
  return ACCESS_POLICY_PRESETS.find((p) => p.id === id);
}

export function moduleSetKey(ids: readonly string[]): string {
  return [...new Set(ids)].sort().join(",");
}

/** Returns a preset if the user's modules match exactly; otherwise null (custom mix). */
export function matchAccessPolicyForModules(allowedModules: readonly string[]): AccessPolicyPreset | null {
  const key = moduleSetKey(allowedModules);
  for (const p of ACCESS_POLICY_PRESETS) {
    if (moduleSetKey(p.moduleIds) === key) return p;
  }
  return null;
}

export function presetModuleSet(id: AccessPolicyId): Set<string> {
  const p = getAccessPolicyPreset(id);
  return new Set(p?.moduleIds ?? []);
}
