/** Canonical module IDs for RBAC / admin (aligned with product nav + admin). */

export type AccessModuleId =
  | "dashboard"
  | "cases"
  | "disputes"
  | "graph"
  | "investigation"
  | "osint"
  | "analytics"
  | "rules"
  | "entity-lists"
  | "shadow"
  | "simulation"
  | "compliance"
  | "integrations"
  | "notifications"
  | "settings"
  | "admin";

export type AccessGroupId =
  | "operations"
  | "investigation"
  | "policy_testing"
  | "governance"
  | "account"
  | "administration";

export type ModuleCatalogEntry = {
  id: AccessModuleId;
  label: string;
  route: string;
  /** Changes touching core modules need ≥2 approvers. */
  core?: boolean;
  /** Elevated scrutiny + maker–checker when granting or editing. */
  highRisk?: boolean;
};

export const ACCESS_GROUPS: { id: AccessGroupId; label: string; modules: ModuleCatalogEntry[] }[] = [
  {
    id: "operations",
    label: "Operations",
    modules: [
      { id: "dashboard", label: "Dashboard", route: "/dashboard" },
      { id: "cases", label: "Cases", route: "/cases" },
      { id: "disputes", label: "Disputes", route: "/disputes" },
    ],
  },
  {
    id: "investigation",
    label: "Investigation",
    modules: [
      { id: "graph", label: "Graph Explorer", route: "/graph", highRisk: true },
      { id: "investigation", label: "Investigation Copilot", route: "/investigation", highRisk: true },
      { id: "osint", label: "OSINT", route: "/osint", highRisk: true },
      { id: "analytics", label: "Analytics", route: "/analytics" },
    ],
  },
  {
    id: "policy_testing",
    label: "Policy & testing",
    modules: [
      { id: "rules", label: "Rules", route: "/rules", core: true, highRisk: true },
      { id: "entity-lists", label: "Entity Lists", route: "/entity-lists", core: true, highRisk: true },
      { id: "shadow", label: "Shadow Mode", route: "/shadow", highRisk: true },
      { id: "simulation", label: "Simulation", route: "/simulation", highRisk: true },
    ],
  },
  {
    id: "governance",
    label: "Governance",
    modules: [
      { id: "compliance", label: "Compliance", route: "/compliance", highRisk: true },
      { id: "integrations", label: "Integrations", route: "/integrations", core: true, highRisk: true },
    ],
  },
  {
    id: "account",
    label: "Account",
    modules: [
      { id: "notifications", label: "Notifications", route: "/notifications" },
      { id: "settings", label: "Settings", route: "/settings" },
    ],
  },
  {
    id: "administration",
    label: "Administration",
    modules: [{ id: "admin", label: "Admin Panel", route: "/admin", core: true, highRisk: true }],
  },
];

export function allAccessModuleIds(): AccessModuleId[] {
  return ACCESS_GROUPS.flatMap((g) => g.modules.map((m) => m.id));
}

export function moduleMeta(id: AccessModuleId): ModuleCatalogEntry | undefined {
  for (const g of ACCESS_GROUPS) {
    const m = g.modules.find((x) => x.id === id);
    if (m) return m;
  }
  return undefined;
}

/** Any add/remove touching core or high-risk modules needs ≥2 distinct approvers. */
export function requiresMakerChecker(
  previouslyAllowed: Set<string>,
  nextAllowed: Set<string>,
): { required: boolean; reason: string; riskTier: "standard" | "high" | "core" } {
  const touched = new Set<string>();
  for (const id of nextAllowed) {
    if (!previouslyAllowed.has(id)) touched.add(id);
  }
  for (const id of previouslyAllowed) {
    if (!nextAllowed.has(id)) touched.add(id);
  }
  for (const id of touched) {
    const meta = moduleMeta(id as AccessModuleId);
    if (meta?.core) {
      return {
        required: true,
        reason: `Change affects core module: ${meta.label}`,
        riskTier: "core",
      };
    }
  }
  const highIds = [...touched].filter((id) => moduleMeta(id as AccessModuleId)?.highRisk);
  if (highIds.length > 0) {
    const labels = highIds.map((id) => moduleMeta(id as AccessModuleId)?.label ?? id).join(", ");
    return {
      required: true,
      reason: `Change affects high-risk module(s): ${labels}`,
      riskTier: "high",
    };
  }
  return { required: false, reason: "", riskTier: "standard" };
}
