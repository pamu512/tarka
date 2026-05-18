import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Routes, Route, NavLink, Navigate } from "react-router-dom";
import { MicroDevOnboardingGate } from "./components/MicroDevOnboardingGate";
import { RequireRole } from "./components/rbac/RequireRole";
import { getDataSourceSnapshot, subscribeDataSource } from "./api/dataSourceState";
import { AnalystCaseTabBar } from "./components/AnalystCaseTabBar";
import { AppTopBar } from "./components/AppTopBar";
import { AnalystReadinessBar } from "./components/AnalystReadinessBar";
import { CommandPalette } from "./components/CommandPalette";
import { ModuleIcon, type ModuleId } from "./components/ModuleIcon";
import { TarkaLogo } from "./components/TarkaLogo";
import MlLifecycle from "./pages/MlLifecycle";
import OpsCalibration from "./pages/OpsCalibration";
import { TarkaRbacRole } from "./security/rbacConstants";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const TarkaCommandCenter = lazy(() => import("./pages/TarkaCommandCenter"));
const Cases = lazy(() => import("./pages/Cases"));
const WorkloadBalancer = lazy(() => import("./pages/WorkloadBalancer"));
const BulkTriage = lazy(() => import("./pages/BulkTriage"));
const CaseComparisonMode = lazy(() => import("./pages/CaseComparisonMode"));
const CaseDetail = lazy(() => import("./pages/CaseDetail"));
const SarIntentDetailPage = lazy(() => import("./pages/SarIntentDetailPage"));
const Disputes = lazy(() => import("./pages/Disputes"));
const DisputeReviewByIdPage = lazy(() => import("./pages/disputes/[id]"));
const Rules = lazy(() => import("./pages/Rules"));
const GraphExplorer = lazy(() => import("./pages/GraphExplorer"));
const LinkAnalysisPage = lazy(() => import("./pages/LinkAnalysisPage"));
const Analytics = lazy(() => import("./pages/Analytics"));
const RulePerformance = lazy(() => import("./pages/RulePerformance"));
const AuditLogExplorer = lazy(() => import("./pages/AuditLogExplorer"));
const Investigation = lazy(() => import("./pages/Investigation"));
const DagTracePage = lazy(() => import("./pages/DagTracePage"));
const ShadowLlmForensics = lazy(() => import("./pages/ShadowLlmForensics"));
const OsintEnrichment = lazy(() => import("./pages/OsintEnrichment"));
const NatsSetuMonitor = lazy(() => import("./pages/NatsSetuMonitor"));
const ShadowMode = lazy(() => import("./pages/ShadowMode"));
const Simulation = lazy(() => import("./pages/Simulation"));
const BacktestJobConfigurator = lazy(() => import("./pages/BacktestJobConfigurator"));
const Compliance = lazy(() => import("./pages/Compliance"));
const OpsCounters = lazy(() => import("./pages/OpsCounters"));
const OpsPipelines = lazy(() => import("./pages/OpsPipelines"));
const OpsSarTransportBoard = lazy(() => import("./pages/OpsSarTransportBoard"));
const OpsInfraDashboard = lazy(() => import("./pages/OpsInfraDashboard"));
const FeatureTools = lazy(() => import("./pages/FeatureTools"));
const EntityLists = lazy(() => import("./pages/EntityLists"));
const Integrations = lazy(() => import("./pages/Integrations"));
const Notifications = lazy(() => import("./pages/Notifications"));
const Settings = lazy(() => import("./pages/Settings"));
const Help = lazy(() => import("./pages/Help"));
const AdminPanel = lazy(() => import("./pages/AdminPanel"));
const VisualRuleBuilder = lazy(() => import("./pages/VisualRuleBuilder"));
const ExecutiveDashboards = lazy(() => import("./pages/ExecutiveDashboards"));
const ForbiddenUnauthorized = lazy(() => import("./pages/ForbiddenUnauthorized"));
const TransactionsLiveGrid = lazy(() => import("./pages/TransactionsLiveGrid"));
const PitMlParquetExport = lazy(() => import("./pages/PitMlParquetExport"));
const SystemHealthHud = lazy(() => import("./pages/SystemHealthHud"));
const SystemBenchmarking = lazy(() => import("./pages/SystemBenchmarking"));
const MulePathVisualizer = lazy(() => import("./pages/MulePathVisualizer"));
const PromoAbuseDashboard = lazy(() => import("./pages/PromoAbuseDashboard"));
const SyntheticIdentityDetectors = lazy(() => import("./pages/SyntheticIdentityDetectors"));
const SellerIntegrityDashboard = lazy(() => import("./pages/SellerIntegrityDashboard"));
const PayoutDelayAutomation = lazy(() => import("./pages/PayoutDelayAutomation"));
const SocialEngineeringMonitor = lazy(() => import("./pages/SocialEngineeringMonitor"));
const ReviewRingClusters = lazy(() => import("./pages/ReviewRingClusters"));
const FailoverTogglesPage = lazy(() => import("./pages/FailoverTogglesPage"));
const DeadLetterOffice = lazy(() => import("./pages/DeadLetterOffice"));
const VersionedRuleControl = lazy(() => import("./pages/VersionedRuleControl"));
const AutomatedBackupIndicators = lazy(() => import("./pages/AutomatedBackupIndicators"));
const WebhookLogs = lazy(() => import("./pages/WebhookLogs"));
const RateLimitShields = lazy(() => import("./pages/RateLimitShields"));
const EncryptedFieldToggles = lazy(() => import("./pages/EncryptedFieldToggles"));
const KycHandover = lazy(() => import("./pages/KycHandover"));
const RegionalRiskToggles = lazy(() => import("./pages/RegionalRiskToggles"));

type NavBadge = { count: number; kind: "action" | "info" };

type NavItem = {
  to: string;
  label: string;
  module: ModuleId;
  /** Demo counts — replace with live queue/API when wired. */
  badge?: NavBadge;
};

const SHOW_DEMO_BADGES = ((import.meta.env.VITE_SHOW_DEMO_BADGES as string | undefined) ?? "false").trim().toLowerCase() === "true";

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Operations",
    items: [
      { to: "/command-center", label: "Command Center", module: "dashboard" },
      { to: "/dashboard", label: "Classic dashboard", module: "dashboard" },
      { to: "/exec-dashboards", label: "Executive KPIs", module: "dashboard" },
      { to: "/cases", label: "Cases", module: "cases", badge: SHOW_DEMO_BADGES ? { count: 3, kind: "action" } : undefined },
      { to: "/ops/workload", label: "Workload Balancer", module: "cases" },
      { to: "/disputes", label: "Disputes", module: "disputes", badge: SHOW_DEMO_BADGES ? { count: 1, kind: "action" } : undefined },
    ],
  },
  {
    label: "Investigation",
    items: [
      { to: "/graph", label: "Graph Explorer", module: "graph" },
      { to: "/graph/link-analysis", label: "Link analysis (2D)", module: "graph" },
      { to: "/graph/mule-path", label: "Mule path", module: "graph" },
      { to: "/investigation", label: "Investigation Copilot", module: "investigation" },
      { to: "/investigation/dag-trace", label: "DAG trace", module: "investigation" },
      { to: "/investigation/shadow-llm", label: "Shadow LLM forensics", module: "investigation" },
      {
        to: "/investigation/synthetic-identity",
        label: "Synthetic identity",
        module: "investigation",
      },
      {
        to: "/investigation/social-engineering",
        label: "Social engineering",
        module: "investigation",
      },
      { to: "/osint", label: "OSINT", module: "osint" },
      { to: "/osint/nats-setu-monitor", label: "NATS Setu monitor", module: "osint" },
      { to: "/analytics", label: "Analytics", module: "analytics" },
      { to: "/analytics/rule-performance", label: "Rule performance", module: "analytics" },
      { to: "/analytics/promo-abuse", label: "Promo abuse", module: "analytics" },
      { to: "/analytics/review-rings", label: "Review rings", module: "analytics" },
      { to: "/transactions/live", label: "Live transactions", module: "analytics" },
      { to: "/analytics/audit-log", label: "Audit Log Explorer", module: "analytics" },
      { to: "/ops/ml-lifecycle", label: "ML lifecycle", module: "analytics" },
      { to: "/ops/ml-parquet-export", label: "PIT Parquet export", module: "analytics" },
    ],
  },
  {
    label: "Policy & testing",
    items: [
      { to: "/rules", label: "Rules", module: "rules" },
      { to: "/rules/visual", label: "Visual rule builder", module: "rules" },
      { to: "/rules/version-control", label: "Versioned rule control", module: "rules" },
      { to: "/entity-lists", label: "Entity Lists", module: "entity-lists" },
      { to: "/shadow", label: "Shadow Mode", module: "shadow" },
      { to: "/simulation", label: "Simulation", module: "simulation" },
      { to: "/ops/backtest", label: "Backtest jobs", module: "rules" },
    ],
  },
  {
    label: "Governance",
    items: [
      { to: "/compliance", label: "Compliance", module: "compliance", badge: SHOW_DEMO_BADGES ? { count: 1, kind: "info" } : undefined },
      { to: "/compliance/encrypted-fields", label: "Encrypted field toggles", module: "compliance" },
      { to: "/compliance/kyc-handover", label: "KYC handover", module: "compliance" },
      { to: "/compliance/regional-risk", label: "Regional risk", module: "compliance" },
      { to: "/ops/calibration", label: "Calibration & drift", module: "analytics" },
      { to: "/ops/counters", label: "Counters catalog", module: "compliance" },
      { to: "/ops/features", label: "Feature tools", module: "compliance" },
      { to: "/ops/pipelines", label: "ETL / pipelines", module: "compliance" },
      { to: "/ops/sar-transport", label: "SAR SFTP worker", module: "compliance" },
      { to: "/ops/infra", label: "Infra & health", module: "compliance" },
      { to: "/ops/system-health", label: "System health HUD", module: "compliance" },
      { to: "/ops/system-benchmarking", label: "System benchmarking", module: "compliance" },
      { to: "/ops/failover-toggles", label: "Failover toggles", module: "compliance" },
      { to: "/ops/dead-letter", label: "Dead Letter Office", module: "compliance" },
      { to: "/ops/backups", label: "Automated backup", module: "compliance" },
      { to: "/integrations", label: "Integrations", module: "integrations" },
      { to: "/integrations/webhook-logs", label: "Webhook logs", module: "integrations" },
      { to: "/integrations/rate-limit-shields", label: "Rate limit shields", module: "integrations" },
      { to: "/integrations/seller-integrity", label: "Seller integrity", module: "integrations" },
      { to: "/integrations/payout-delay", label: "Payout delay", module: "integrations" },
      { to: "/admin", label: "Admin Panel", module: "admin" },
    ],
  },
];

/** Demo counts are opt-in so production-like runs do not imply false confidence. */
const NOTIFICATION_ACTIONABLE_COUNT = SHOW_DEMO_BADGES ? 2 : 0;

function BadgePill({ badge, degradedTitle }: { badge: NavBadge; degradedTitle?: string }) {
  if (degradedTitle) {
    return (
      <span
        className="ml-auto shrink-0 min-w-[1.125rem] h-5 px-1 rounded-full text-[10px] font-semibold flex items-center justify-center tabular-nums bg-rose-500/20 text-rose-300 border border-rose-500/30"
        aria-label="Queue indicator degraded"
        title={degradedTitle}
      >
        !
      </span>
    );
  }
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

function formatFreshness(ts: number): string {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export default function App() {
  const [dataSource, setDataSource] = useState(() => getDataSourceSnapshot());

  useEffect(() => subscribeDataSource(() => setDataSource(getDataSourceSnapshot())), []);

  const queueSignalDegraded = dataSource.outcome !== "live";
  const notificationActionableCount = queueSignalDegraded ? 0 : NOTIFICATION_ACTIONABLE_COUNT;
  const queueDegradedTitle = useMemo(
    () => `Queue signal degraded: ${dataSource.outcome} data. Last refresh ${formatFreshness(dataSource.updatedAt)}.`,
    [dataSource.outcome, dataSource.updatedAt],
  );

  return (
    <MicroDevOnboardingGate>
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
                      {item.to === "/cases" && queueSignalDegraded ? (
                        <BadgePill badge={{ count: 1, kind: "info" }} degradedTitle={queueDegradedTitle} />
                      ) : item.badge ? (
                        <BadgePill badge={item.badge} />
                      ) : null}
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
        <AppTopBar notificationActionableCount={notificationActionableCount} />
        <AnalystReadinessBar />
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
            <Route path="/" element={<Navigate to="/command-center" replace />} />
            <Route path="/command-center" element={<TarkaCommandCenter />} />
            <Route path="/403-unauthorized" element={<ForbiddenUnauthorized />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/exec-dashboards" element={<ExecutiveDashboards />} />
            <Route path="/cases" element={<Cases />} />
            <Route path="/ops/workload" element={<WorkloadBalancer />} />
            <Route path="/cases/bulk-triage" element={<BulkTriage />} />
            <Route path="/cases/compare" element={<CaseComparisonMode />} />
            <Route path="/cases/:caseId/sar-intent/:intentId" element={<SarIntentDetailPage />} />
            <Route path="/cases/:caseId" element={<CaseDetail />} />
            <Route path="/disputes/:id" element={<DisputeReviewByIdPage />} />
            <Route path="/disputes" element={<Disputes />} />
            <Route path="/rules" element={<Rules />} />
            <Route
              path="/rules/visual"
              element={
                <RequireRole allow={TarkaRbacRole.RiskArchitect}>
                  <VisualRuleBuilder />
                </RequireRole>
              }
            />
            <Route
              path="/rules/version-control"
              element={
                <RequireRole allow={TarkaRbacRole.RiskArchitect}>
                  <VersionedRuleControl />
                </RequireRole>
              }
            />
            <Route path="/entity-lists" element={<EntityLists />} />
            <Route path="/shadow" element={<ShadowMode />} />
            <Route path="/simulation" element={<Simulation />} />
            <Route path="/ops/backtest" element={<BacktestJobConfigurator />} />
            <Route path="/graph" element={<GraphExplorer />} />
            <Route path="/graph/link-analysis" element={<LinkAnalysisPage />} />
            <Route path="/graph/mule-path" element={<MulePathVisualizer />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/analytics/rule-performance" element={<RulePerformance />} />
            <Route path="/analytics/promo-abuse" element={<PromoAbuseDashboard />} />
            <Route path="/analytics/review-rings" element={<ReviewRingClusters />} />
            <Route path="/analytics/audit-log" element={<AuditLogExplorer />} />
            <Route path="/transactions/live" element={<TransactionsLiveGrid />} />
            <Route path="/ops/calibration" element={<OpsCalibration />} />
            <Route path="/ops/ml-lifecycle" element={<MlLifecycle />} />
            <Route path="/ops/ml-parquet-export" element={<PitMlParquetExport />} />
            <Route path="/investigation" element={<Investigation />} />
            <Route path="/investigation/dag-trace" element={<DagTracePage />} />
            <Route path="/investigation/shadow-llm" element={<ShadowLlmForensics />} />
            <Route path="/investigation/synthetic-identity" element={<SyntheticIdentityDetectors />} />
            <Route path="/investigation/social-engineering" element={<SocialEngineeringMonitor />} />
            <Route path="/osint" element={<OsintEnrichment />} />
            <Route path="/osint/nats-setu-monitor" element={<NatsSetuMonitor />} />
            <Route path="/compliance/encrypted-fields" element={<EncryptedFieldToggles />} />
            <Route path="/compliance/kyc-handover" element={<KycHandover />} />
            <Route path="/compliance/regional-risk" element={<RegionalRiskToggles />} />
            <Route path="/compliance" element={<Compliance />} />
            <Route path="/ops/counters" element={<OpsCounters />} />
            <Route path="/ops/pipelines" element={<OpsPipelines />} />
            <Route path="/ops/sar-transport" element={<OpsSarTransportBoard />} />
            <Route path="/ops/infra" element={<OpsInfraDashboard />} />
            <Route path="/ops/system-health" element={<SystemHealthHud />} />
            <Route path="/ops/system-benchmarking" element={<SystemBenchmarking />} />
            <Route path="/ops/failover-toggles" element={<FailoverTogglesPage />} />
            <Route path="/ops/dead-letter" element={<DeadLetterOffice />} />
            <Route path="/ops/backups" element={<AutomatedBackupIndicators />} />
            <Route path="/ops/features" element={<FeatureTools />} />
            <Route path="/integrations/webhook-logs" element={<WebhookLogs />} />
            <Route path="/integrations/rate-limit-shields" element={<RateLimitShields />} />
            <Route path="/integrations/seller-integrity" element={<SellerIntegrityDashboard />} />
            <Route path="/integrations/payout-delay" element={<PayoutDelayAutomation />} />
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
    </MicroDevOnboardingGate>
  );
}
