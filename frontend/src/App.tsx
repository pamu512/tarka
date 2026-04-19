import { Suspense, lazy } from "react";
import { Routes, Route, NavLink, Navigate } from "react-router-dom";
import { AnalystCaseTabBar } from "./components/AnalystCaseTabBar";
import { AppTopBar } from "./components/AppTopBar";
import { CommandPalette } from "./components/CommandPalette";
import { ModuleIcon, type ModuleId } from "./components/ModuleIcon";
import { TarkaLogo } from "./components/TarkaLogo";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Cases = lazy(() => import("./pages/Cases"));
const CaseDetail = lazy(() => import("./pages/CaseDetail"));
const Disputes = lazy(() => import("./pages/Disputes"));
const Rules = lazy(() => import("./pages/Rules"));
const GraphExplorer = lazy(() => import("./pages/GraphExplorer"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Investigation = lazy(() => import("./pages/Investigation"));
const OsintEnrichment = lazy(() => import("./pages/OsintEnrichment"));
const ShadowMode = lazy(() => import("./pages/ShadowMode"));
const Simulation = lazy(() => import("./pages/Simulation"));
const Compliance = lazy(() => import("./pages/Compliance"));
const OpsCounters = lazy(() => import("./pages/OpsCounters"));
const OpsPipelines = lazy(() => import("./pages/OpsPipelines"));
const FeatureTools = lazy(() => import("./pages/FeatureTools"));
const EntityLists = lazy(() => import("./pages/EntityLists"));
const Integrations = lazy(() => import("./pages/Integrations"));
const Notifications = lazy(() => import("./pages/Notifications"));
const Settings = lazy(() => import("./pages/Settings"));
const Help = lazy(() => import("./pages/Help"));
const AdminPanel = lazy(() => import("./pages/AdminPanel"));

type NavBadge = { count: number; kind: "action" | "info" };

type NavItem = {
  to: string;
  label: string;
  module: ModuleId;
  /** Demo counts — replace with live queue/API when wired. */
  badge?: NavBadge;
};

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Operations",
    items: [
      { to: "/dashboard", label: "Dashboard", module: "dashboard" },
      { to: "/cases", label: "Cases", module: "cases", badge: { count: 3, kind: "action" } },
      { to: "/disputes", label: "Disputes", module: "disputes", badge: { count: 1, kind: "action" } },
    ],
  },
  {
    label: "Investigation",
    items: [
      { to: "/graph", label: "Graph Explorer", module: "graph" },
      { to: "/investigation", label: "Investigation Copilot", module: "investigation" },
      { to: "/osint", label: "OSINT", module: "osint" },
      { to: "/analytics", label: "Analytics", module: "analytics" },
    ],
  },
  {
    label: "Policy & testing",
    items: [
      { to: "/rules", label: "Rules", module: "rules" },
      { to: "/entity-lists", label: "Entity Lists", module: "entity-lists" },
      { to: "/shadow", label: "Shadow Mode", module: "shadow" },
      { to: "/simulation", label: "Simulation", module: "simulation" },
    ],
  },
  {
    label: "Governance",
    items: [
      { to: "/compliance", label: "Compliance", module: "compliance", badge: { count: 1, kind: "info" } },
      { to: "/ops/counters", label: "Counters catalog", module: "compliance" },
      { to: "/ops/features", label: "Feature tools", module: "compliance" },
      { to: "/ops/pipelines", label: "ETL / pipelines", module: "compliance" },
      { to: "/integrations", label: "Integrations", module: "integrations" },
      { to: "/admin", label: "Admin Panel", module: "admin" },
    ],
  },
];

/** Demo: actionable items surfaced in Notifications — replace with real counts. */
const NOTIFICATION_ACTIONABLE_COUNT = 2;

function BadgePill({ badge }: { badge: NavBadge }) {
  if (badge.count <= 0) return null;
  const shown = badge.count > 99 ? "99+" : String(badge.count);
  const cls =
    badge.kind === "action"
      ? "bg-amber-500/90 text-black"
      : "bg-surface-600 text-gray-200";
  return (
    <span
      className={`ml-auto shrink-0 min-w-[1.125rem] h-5 px-1 rounded-full text-[10px] font-semibold flex items-center justify-center tabular-nums ${cls}`}
      aria-label={`${badge.count} updates`}
    >
      {shown}
    </span>
  );
}

export default function App() {
  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-60 flex-shrink-0 bg-surface-900 border-r border-surface-700 flex flex-col">
        <div className="h-16 flex items-center px-5 border-b border-surface-700">
          <TarkaLogo />
        </div>

        <nav className="flex-1 py-3 px-3 overflow-y-auto flex flex-col min-h-0">
          <div className="space-y-0 flex-1">
            {NAV_GROUPS.map((group, gi) => (
              <div key={group.label}>
                {gi > 0 && (
                  <div
                    className="my-2.5 mx-1 h-px bg-surface-700/90"
                    role="separator"
                    aria-hidden
                  />
                )}
                <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-600">
                  {group.label}
                </div>
                <div className="space-y-0.5">
                  {group.items.map((item) => (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      className={({ isActive }) =>
                        `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors min-w-0 ${
                          isActive
                            ? "bg-brand-600/20 text-brand-400"
                            : "text-gray-400 hover:bg-surface-700 hover:text-gray-200"
                        }`
                      }
                    >
                      <ModuleIcon module={item.module} className="w-[1.125rem] h-[1.125rem] opacity-90 shrink-0" aria-hidden />
                      <span className="truncate">{item.label}</span>
                      {item.badge ? <BadgePill badge={item.badge} /> : null}
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </nav>

        <div className="px-4 py-3 border-t border-surface-700">
          <div className="text-xs text-gray-500">Tarka v1.0</div>
          <div className="text-xs text-gray-600 mt-0.5">
            Prove every signal.
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col bg-surface-950">
        <AppTopBar notificationActionableCount={NOTIFICATION_ACTIONABLE_COUNT} />
        <AnalystCaseTabBar />
        <CommandPalette />
        <main className="min-h-0 flex-1 overflow-y-auto">
        <Suspense
          fallback={
            <div className="h-full w-full flex items-center justify-center">
              <div className="w-8 h-8 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
            </div>
          }
        >
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/cases" element={<Cases />} />
            <Route path="/cases/:caseId" element={<CaseDetail />} />
            <Route path="/disputes" element={<Disputes />} />
            <Route path="/rules" element={<Rules />} />
            <Route path="/entity-lists" element={<EntityLists />} />
            <Route path="/shadow" element={<ShadowMode />} />
            <Route path="/simulation" element={<Simulation />} />
            <Route path="/graph" element={<GraphExplorer />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/investigation" element={<Investigation />} />
            <Route path="/osint" element={<OsintEnrichment />} />
            <Route path="/compliance" element={<Compliance />} />
            <Route path="/ops/counters" element={<OpsCounters />} />
            <Route path="/ops/pipelines" element={<OpsPipelines />} />
            <Route path="/ops/features" element={<FeatureTools />} />
            <Route path="/integrations" element={<Integrations />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/help" element={<Help />} />
            <Route path="/admin" element={<AdminPanel />} />
          </Routes>
        </Suspense>
        </main>
      </div>
    </div>
  );
}
