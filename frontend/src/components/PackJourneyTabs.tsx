import { NavLink } from "react-router";

/**
 * One pack journey, five existing surfaces. Route shell only — pages stay
 * authoritative; this strip just keeps the author→observe→backtest→promote→
 * monitor loop one click apart on every stage page.
 */
const STAGES = [
  { to: "/rules", label: "Author", hint: "sentence / canvas / JSON" },
  { to: "/observe", label: "Observe", hint: "shadow canary" },
  { to: "/ops/backtest", label: "Backtest", hint: "warehouse jobs" },
  { to: "/ops/shadow", label: "Promote", hint: "gates + confirm" },
  { to: "/analytics/rule-performance", label: "Monitor", hint: "telemetry + drift" },
] as const;

export function PackJourneyTabs() {
  return (
    <nav
      aria-label="Pack journey"
      className="flex items-center gap-1 border-b border-surface-700 pb-2 mb-4 overflow-x-auto"
    >
      {STAGES.map((s, i) => (
        <NavLink
          key={s.to}
          to={s.to}
          title={s.hint}
          className={({ isActive }) =>
            `px-3 py-1.5 text-xs rounded-lg whitespace-nowrap transition-colors ${
              isActive
                ? "bg-brand-600/20 text-brand-400 border border-brand-500/40 font-medium"
                : "text-gray-400 hover:text-gray-200 hover:bg-surface-700 border border-transparent"
            }`
          }
        >
          <span className="text-gray-600 mr-1 font-mono">{i + 1}</span>
          {s.label}
        </NavLink>
      ))}
    </nav>
  );
}
