import type { ReactNode, SVGProps } from "react";

export type ModuleId =
  | "dashboard"
  | "cases"
  | "disputes"
  | "rules"
  | "entity-lists"
  | "shadow"
  | "simulation"
  | "graph"
  | "investigation"
  | "osint"
  | "analytics"
  | "compliance"
  | "integrations"
  | "notifications"
  | "settings"
  | "admin"
  | "help";

type IconProps = SVGProps<SVGSVGElement> & { className?: string };

function iconBase(props: IconProps) {
  const { className = "w-5 h-5", ...rest } = props;
  return { className: `shrink-0 ${className}`, ...rest };
}

/** Decision API — live decisions / audit pulse */
function IconDashboard(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M4 19V5M4 19h16M4 19l3-6 4 3 5-8 4 5" />
      <circle cx="7" cy="8" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** Case API — case queue */
function IconCases(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M8 6h13M8 6a2 2 0 100-4H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8a2 2 0 00-2-2h-2" />
      <path d="M8 10h8M8 14h5" />
    </svg>
  );
}

/** Disputes / chargebacks */
function IconDisputes(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="M2 10h20M7 15h.01M11 15h2" />
    </svg>
  );
}

/** Rules + OPA policy */
function IconRules(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M9 12l2 2 4-4" />
      <path d="M4 4h16v16H4V4z" />
      <path d="M8 2v4M16 2v4" />
    </svg>
  );
}

/** Entity lists (decision-api lists) */
function IconEntityLists(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M8 6h13M8 12h13M8 18h13M4 6h.01M4 12h.01M4 18h.01" />
    </svg>
  );
}

/** Shadow / observation mode */
function IconShadow(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  );
}

/** Simulation / what-if */
function IconSimulation(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M9 3H5a2 2 0 00-2 2v4M15 3h4a2 2 0 012 2v4M9 21H5a2 2 0 01-2-2v-4M15 21h4a2 2 0 002-2v-4" />
      <path d="M12 8v8M9 15l3 3 3-3" />
    </svg>
  );
}

/** Graph service / Neo4j explorer */
function IconGraph(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <circle cx="5" cy="6" r="2.5" />
      <circle cx="19" cy="6" r="2.5" />
      <circle cx="12" cy="18" r="2.5" />
      <path d="M7 7.5l5 8M17 7.5l-5 8" />
    </svg>
  );
}

/** Investigation Copilot (AI assistant) */
function IconInvestigation(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M12 3a7 7 0 015.74 11l3.26 3.26a1 1 0 01-1.42 1.42L16.26 15.7A7 7 0 115 10a7 7 0 017-7z" />
      <path d="M9.5 10h.01M12 12h.01M14.5 10h.01" />
    </svg>
  );
}

/** OSINT / integration-ingress enrichment */
function IconOsint(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20M12 2a15 15 0 010 20M12 2a15 15 0 000 20" />
    </svg>
  );
}

/** Analytics sink / ClickHouse metrics */
function IconAnalytics(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M4 19V5M4 19h16M8 15v-4M12 19V9M16 13v-3" />
    </svg>
  );
}

/** Compliance / privacy evidence */
function IconCompliance(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M12 3l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V7l8-4z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

/** Integrations catalog / ingress */
function IconIntegrations(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function IconNotifications(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M18 8a6 6 0 10-12 0c0 7-3 7-3 7h18s-3 0-3-7" />
      <path d="M13.73 21a2 2 0 01-3.46 0" />
    </svg>
  );
}

function IconSettings(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
    </svg>
  );
}

/** Admin / RBAC console */
function IconAdmin(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <path d="M14 14h7v7h-7zM17 17h.01" />
    </svg>
  );
}

function IconHelp(p: IconProps) {
  const x = iconBase(p);
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...x}>
      <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
      <path d="M8 7h8M8 11h6" />
      <circle cx="12" cy="15.5" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

const ICONS: Record<ModuleId, (p: IconProps) => ReactNode> = {
  dashboard: IconDashboard,
  cases: IconCases,
  disputes: IconDisputes,
  rules: IconRules,
  "entity-lists": IconEntityLists,
  shadow: IconShadow,
  simulation: IconSimulation,
  graph: IconGraph,
  investigation: IconInvestigation,
  osint: IconOsint,
  analytics: IconAnalytics,
  compliance: IconCompliance,
  integrations: IconIntegrations,
  notifications: IconNotifications,
  settings: IconSettings,
  admin: IconAdmin,
  help: IconHelp,
};

export function ModuleIcon({ module, ...props }: { module: ModuleId } & IconProps) {
  const Cmp = ICONS[module];
  return <Cmp {...props} />;
}

/** Product mark — aligns with “prove every signal” (shield + signal) */
export function TarkaMark(p: IconProps) {
  const x = iconBase({ ...p, className: p.className ?? "w-8 h-8 text-brand-400" });
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden {...x}>
      <path
        d="M16 3L5 8v8c0 5.5 4 10.5 11 13 7-2.5 11-7.5 11-13V8L16 3z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      <path d="M11 16h10M16 11v10" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  );
}
