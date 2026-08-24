import type { ReactNode } from "react";
import { PageTitle } from "../components/PageTitle";
import { TarkaLogo } from "../components/TarkaLogo";
import { LEAN_NAV, isPlaneEnabled, visibleLeanNavPaths } from "../config/leanNav";

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-6 space-y-3">
      <h2 className="text-lg font-semibold text-gray-100 border-b border-surface-700 pb-2">{title}</h2>
      <div className="text-sm text-gray-400 leading-relaxed space-y-2">{children}</div>
    </section>
  );
}

function Sub({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <h3 className="text-sm font-medium text-gray-300">{title}</h3>
      <div className="text-sm text-gray-500 pl-0 space-y-1.5">{children}</div>
    </div>
  );
}

const DESK_PATHS = visibleLeanNavPaths();

export default function Help() {
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-10 animate-fade-in pb-20">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-6">
        <TarkaLogo variant="full" className="sm:pr-4 sm:border-r border-surface-700 sm:items-start" />
        <div>
          <PageTitle module="help">Help &amp; guide</PageTitle>
          <p className="text-sm text-gray-500 -mt-2 max-w-2xl">
            How the production desk is organized and what to do first. Use{" "}
            <strong className="text-gray-400">Settings → Appearance</strong> for light, dark, or system theme.
          </p>
        </div>
      </div>

      <nav className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 text-sm text-gray-400">
        <div className="text-xs font-semibold uppercase tracking-wide text-gray-600 mb-2">On this page</div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {[
            ["#overview", "Overview"],
            ["#desk", "Desk paths"],
            ["#cases", "Cases"],
            ["#decisions", "Decisions"],
            ["#graph-rules", "Graph and rules"],
            ["#ops", "Ops"],
            ["#account", "Settings"],
          ].map(([href, label]) => (
            <li key={href}>
              <a href={href} className="text-brand-400 hover:text-brand-300">
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <Section id="overview" title="Overview">
        <p>
          Tarka is a fraud operations desk: case queue, decision audit, graph, rules, and a small ops strip in one
          shell. The left nav lists the production surface
          {LEAN_NAV ? " (lean mode — brochure modules are not registered)" : ""}. The{" "}
          <strong className="text-gray-400">top bar</strong> starts with tenant + environment (environment is a{" "}
          <strong className="text-gray-400">display label</strong>), then{" "}
          <strong className="text-gray-400">Search / jump</strong> (
          <kbd className="px-1 rounded bg-surface-800 border border-surface-600 text-gray-400">⌘K</kbd> /{" "}
          <kbd className="px-1 rounded bg-surface-800 border border-surface-600 text-gray-400">Ctrl+K</kbd>
          ), Help, Settings, and Sign out.
        </p>
        <p>
          <strong className="text-gray-400">Open cases:</strong> opening a case from the queue adds a tab under the top
          bar. Tabs persist for this browser session. Case detail uses{" "}
          <code className="text-gray-500">?tab=</code> (timeline / audit / graph) so links are shareable. Disposition
          (reason code + Resolve / Close / keep investigating) lives in the sticky bar at the top of{" "}
          <code className="text-gray-500">/cases/:id</code>.
        </p>
        <p>
          In the command palette, type <code className="text-gray-500">tenant_id/case_id</code> to open a case in a
          specific tenant; a bare case id uses the workspace tenant from the top bar (default{" "}
          <code className="text-gray-500">demo</code>). Use{" "}
          <kbd className="px-1 rounded bg-surface-800 border border-surface-600 text-gray-400">↑</kbd>{" "}
          <kbd className="px-1 rounded bg-surface-800 border border-surface-600 text-gray-400">↓</kbd> and{" "}
          <kbd className="px-1 rounded bg-surface-800 border border-surface-600 text-gray-400">Enter</kbd> to run a
          highlighted result.
        </p>
      </Section>

      <Section id="desk" title="Production desk paths">
        <p>
          These routes are the production lean surface. Case and dispute deep links (
          <code className="text-gray-500">/cases/:id</code>, <code className="text-gray-500">/disputes/:id</code>) stay
          reachable even when they are not listed in the sidebar.
        </p>
        <ul className="list-disc pl-5 space-y-1 font-mono text-xs text-gray-400">
          {DESK_PATHS.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      </Section>

      <Section id="cases" title="Cases">
        <Sub title="Queue (/cases)">
          <p>
            Table-first investigation queue from the case service. Filters and the table are the default fold. KPI /
            cohort / desk-activity sit in a closed ops snapshot. Empty tenant: create a case. Filters with no rows:
            clear filters. Approve / Close stay on the existing{" "}
            <code className="text-gray-500">cases.update</code> / bulk update APIs — there is no separate assignment
            API.
          </p>
        </Sub>
        <Sub title="Case detail (/cases/:id)">
          <p>
            Record a verdict from the sticky bar: current status, a reason code, then Resolve, Close, or keep
            investigating. The update goes to <code className="text-gray-500">cases.update</code>. If the case has a{" "}
            <code className="text-gray-500">trace_id</code>, the desk also joins the reason to calibration{" "}
            <code className="text-gray-500">y_label</code>. Missing trace: the case still updates; calibration join is
            skipped.
          </p>
        </Sub>
        <Sub title="Disputes">
          <p>
            Chargebacks and dispute outcomes alongside case context. Open a row at{" "}
            <code className="text-gray-500">/disputes/:id</code>.
          </p>
        </Sub>
      </Section>

      <Section id="decisions" title="Decisions">
        <p>
          Recent decision-api audit rows for this tenant. Fail-closed: an empty or unavailable audit is an empty queue,
          not a mock dashboard. Open a trace from <code className="text-gray-500">/decisions</code> or{" "}
          <code className="text-gray-500">/decisions/:traceId</code>.
        </p>
      </Section>

      <Section id="graph-rules" title="Graph &amp; rules">
        {isPlaneEnabled("graph") ? (
          <Sub title="Graph (/graph)">
            <p>
              Entity neighborhood for the workspace tenant. Tenant is the same workspace id as the top bar (
              <code className="text-gray-500">tarka-workspace-tenant</code>), not a second localStorage key.
            </p>
          </Sub>
        ) : (
          <Sub title="Graph">
            <p>
              Plane off when <code className="text-gray-500">GRAPH_SERVICE_URL</code> is empty. Deep links render
              that state; they do not productize a 503.
            </p>
          </Sub>
        )}
        <Sub title="Rules">
          <p>
            Rule packs and thresholds. Rule performance lives at{" "}
            <code className="text-gray-500">/analytics/rule-performance</code>.
          </p>
        </Sub>
      </Section>

      <Section id="ops" title="Ops">
        <p>
          QA, dispute deadlines, and SAR transport sit on the lean ops strip when those case-api
          routes are in the nav. Calibration and counters appear only when the signals plane URL is
          set. They read live APIs and fail closed when those APIs are down.
        </p>
      </Section>

      <Section id="account" title="Settings">
        <p>
          Workspace appearance (light, dark, or system). Sign out from the account menu clears the browser session
          tokens and returns you to the decision stream. Full OIDC SSO is not on this desk yet.
        </p>
      </Section>
    </div>
  );
}
