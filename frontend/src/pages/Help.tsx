import type { ReactNode } from "react";
import { PageTitle } from "../components/PageTitle";
import { TarkaLogo } from "../components/TarkaLogo";

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

export default function Help() {
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-10 animate-fade-in pb-20">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-6">
        <TarkaLogo variant="full" className="sm:pr-4 sm:border-r border-surface-700 sm:items-start" />
        <div>
          <PageTitle module="help">Help &amp; guide</PageTitle>
          <p className="text-sm text-gray-500 -mt-2 max-w-2xl">
            How the console is organized, what to do first, and where power features live. Use{" "}
            <strong className="text-gray-400">Settings → Appearance</strong> for light, dark, or system theme.
          </p>
        </div>
      </div>

      <nav className="rounded-xl border border-surface-700 bg-surface-900/60 p-4 text-sm text-gray-400">
        <div className="text-xs font-semibold uppercase tracking-wide text-gray-600 mb-2">On this page</div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {[
            ["#overview", "Overview"],
            ["#operations", "Operations"],
            ["#investigation", "Investigation"],
            ["#policy", "Policy & testing"],
            ["#governance", "Governance"],
            ["#account", "Notifications & settings"],
            ["#basics-advanced", "Basics vs advanced"],
            ["#appearance", "Theme & logo"],
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
          Tarka is a fraud operations console: decisions, cases, graph, rules, and governance tools in one shell. The
          left sidebar groups areas by how teams work—queue triage, deep investigation, policy experiments, and
          platform admin. The <strong className="text-gray-400">top bar</strong> on the right has Help, Notifications
          (with an amber count when something needs attention), Settings, and an Account menu for profile context and
          quick access to appearance.
        </p>
        <p>
          This UI is a <strong className="text-gray-400">prototype</strong>: many actions call real or mock APIs. When
          backends are offline, the app falls back to synthetic data so you can still click through flows.
        </p>
      </Section>

      <Section id="operations" title="Operations">
        <Sub title="Dashboard">
          <p>
            High-level pulse: volumes, risk mix, and shortcuts into cases. Use it for stand-ups and sanity checks before
            diving into queues.
          </p>
        </Sub>
        <Sub title="Cases">
          <p>
            Investigation queue from the case service: open a case to see entity, trace, timeline, and links to graph /
            copilot. <strong className="text-gray-400">Basics:</strong> sort and open.{" "}
            <strong className="text-gray-400">Advanced:</strong> labels, comments, SLA hints when wired.
          </p>
        </Sub>
        <Sub title="Disputes">
          <p>
            Chargebacks and dispute outcomes alongside case context. Good for linking fraud decisions to financial
            resolution.
          </p>
        </Sub>
      </Section>

      <Section id="investigation" title="Investigation">
        <Sub title="Graph Explorer">
          <p>
            Entity neighborhood and relationships. <strong className="text-gray-400">Advanced:</strong> use depth and
            filters to hunt rings and shared devices—often high sensitivity, so access may be restricted by policy.
          </p>
        </Sub>
        <Sub title="Investigation Copilot">
          <p>
            AI assistant with tool access to cases, graph, and audits. <strong className="text-gray-400">Basics:</strong>{" "}
            ask for a summary or next steps. <strong className="text-gray-400">Advanced:</strong> preset skills, optional
            platform audit context (with privacy toggles), and <code className="text-gray-500">/skill</code> commands.
          </p>
        </Sub>
        <Sub title="OSINT">
          <p>Open-source enrichment (email, IP, phone, domain). Use for manual verification alongside cases.</p>
        </Sub>
        <Sub title="Analytics">
          <p>Charts and operational metrics. Baseline for volume and mix; pair with rules/simulation for experiments.</p>
        </Sub>
      </Section>

      <Section id="policy" title="Policy & testing">
        <Sub title="Rules">
          <p>
            Rule packs and thresholds (OPA-oriented workflows in production).{" "}
            <strong className="text-gray-400">Advanced:</strong> editing core rules may require approvals and peer review.
          </p>
        </Sub>
        <Sub title="Entity lists">
          <p>Block, allow, and watch lists at entity level—feeds the decision path.</p>
        </Sub>
        <Sub title="Shadow mode">
          <p>Run candidate policies alongside production without affecting live decisions—smoke-test before promote.</p>
        </Sub>
        <Sub title="Simulation">
          <p>Scenario runs and A/B style comparisons on synthetic or sampled traffic—good for what-if analysis.</p>
        </Sub>
      </Section>

      <Section id="governance" title="Governance">
        <Sub title="Compliance">
          <p>Regions, DSAR-style flows, evidence exports—support for audit and privacy programs.</p>
        </Sub>
        <Sub title="Integrations">
          <p>
            Enable providers, run connectivity checks, and vault-style config.{" "}
            <strong className="text-gray-400">Request new integration</strong> submits a ticket for{" "}
            <strong className="text-gray-400">admin approval</strong> before a prefilled GitHub issue is opened for
            engineering.
          </p>
        </Sub>
        <Sub title="Admin Panel">
          <p>
            <strong className="text-gray-400">Basics:</strong> overview counts, active sessions, audit log.{" "}
            <strong className="text-gray-400">Advanced:</strong> module access by user,{" "}
            <strong className="text-gray-400">Groups &amp; policies</strong> (role templates: admin, engineering, data
            science, risk analyst, view only, governance), dual approval for risky RBAC changes, and{" "}
            <strong className="text-gray-400">Integration requests</strong> queue.
          </p>
        </Sub>
      </Section>

      <Section id="account" title="Notifications & settings">
        <Sub title="Notifications">
          <p>Actionable and informational items (demo counts on the nav). Replace with your notification service later.</p>
        </Sub>
        <Sub title="Settings">
          <p>
            Workspace and account placeholders. <strong className="text-gray-400">Appearance</strong> lets you choose
            light, dark, or system default theme.
          </p>
        </Sub>
      </Section>

      <Section id="basics-advanced" title="Basics vs advanced">
        <ul className="list-disc pl-5 space-y-2">
          <li>
            <strong className="text-gray-400">Basics</strong> — navigate modules, open cases, read dashboards, run OSINT
            lookups, toggle integrations, and chat with Copilot using default context.
          </li>
          <li>
            <strong className="text-gray-400">Advanced</strong> — shadow/simulation, rule and list edits, graph depth,
            Copilot audit-context checkboxes, RBAC policy templates, maker–checker approvals, integration request
            approval, and compliance evidence flows.
          </li>
        </ul>
      </Section>

      <Section id="appearance" title="Theme &amp; logo">
        <p>
          The <strong className="text-gray-400">Tarka</strong> mark is a vector stylized “T” from{" "}
          <code className="text-gray-500">/tarka-icon.svg</code> (favicon); the full lockup lives at{" "}
          <code className="text-gray-500">/tarka-logo-full.svg</code>. Both invert with{" "}
          <strong className="text-gray-400">prefers-color-scheme</strong> when used as static files; in the app, the
          sidebar wordmark uses <strong className="text-gray-400">currentColor</strong> so the logo follows your
          Appearance theme.{" "}
          <strong className="text-gray-400">Dark</strong> mode matches the original console look;{" "}
          <strong className="text-gray-400">light</strong> mode inverts surfaces and text grays for readability;{" "}
          <strong className="text-gray-400">system</strong> follows your OS light/dark preference and updates when it
          changes.
        </p>
      </Section>
    </div>
  );
}
