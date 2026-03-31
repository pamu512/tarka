import { Suspense, lazy } from "react";
import { Routes, Route, NavLink, Navigate } from "react-router-dom";

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
const EntityLists = lazy(() => import("./pages/EntityLists"));
const Integrations = lazy(() => import("./pages/Integrations"));

const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard", icon: "\u25A6" },
  { to: "/cases", label: "Cases", icon: "\u2691" },
  { to: "/disputes", label: "Disputes", icon: "\u26A0" },
  { to: "/rules", label: "Rules", icon: "\u2696" },
  { to: "/entity-lists", label: "Entity Lists", icon: "\u2630" },
  { to: "/shadow", label: "Shadow Mode", icon: "\u25D1" },
  { to: "/simulation", label: "Simulation", icon: "\u2697" },
  { to: "/graph", label: "Graph Explorer", icon: "\u2B2F" },
  { to: "/investigation", label: "Investigation", icon: "\u2315" },
  { to: "/osint", label: "OSINT", icon: "\uD83D\uDD0D" },
  { to: "/analytics", label: "Analytics", icon: "\u2587" },
  { to: "/compliance", label: "Compliance", icon: "\uD83D\uDEE1" },
  { to: "/integrations", label: "Integrations", icon: "\uD83E\uDDE9" },
] as const;

export default function App() {
  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-60 flex-shrink-0 bg-surface-900 border-r border-surface-700 flex flex-col">
        <div className="h-16 flex items-center gap-2 px-5 border-b border-surface-700">
          <span className="text-2xl text-brand-400 font-bold tracking-tight">
            T
          </span>
          <span className="text-lg font-semibold text-gray-100 tracking-wide">
            Tarka
          </span>
        </div>

        <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-brand-600/20 text-brand-400"
                    : "text-gray-400 hover:bg-surface-700 hover:text-gray-200"
                }`
              }
            >
              <span className="text-lg leading-none">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="px-4 py-4 border-t border-surface-700">
          <div className="text-xs text-gray-500">Tarka v1.0</div>
          <div className="text-xs text-gray-600 mt-0.5">
            Prove every signal.
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto bg-surface-950">
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
            <Route path="/integrations" element={<Integrations />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}
