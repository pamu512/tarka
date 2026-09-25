import { isPlaneEnabled, DESK_PROFILE } from "@/config/leanNav";

type PlaneHealth = {
  status?: string;
  backend?: string;
  experience_tier?: string;
  degrade_reason?: string;
};

function envRaw(name: string): string {
  return ((import.meta.env as Record<string, string | undefined>)[name] ?? "").trim();
}

/** One operator panel: what's on, what's off, and why. No "coming soon". */
export function ProvisionGlass({
  health,
  deskProfile = DESK_PROFILE,
}: {
  health?: PlaneHealth | null;
  deskProfile?: string;
}) {
  const graphUrl = envRaw("VITE_GRAPH_SERVICE_URL");
  const adviseUrl = envRaw("VITE_INVESTIGATION_AGENT_URL");
  const signalsUrl = envRaw("VITE_SIGNAL_API_URL");
  const huntFlag = envRaw("VITE_HUNT_ENABLED");

  const rows: Array<{ name: string; on: boolean; reason: string }> = [
    {
      name: "Graph (Hunt)",
      on: isPlaneEnabled("graph"),
      reason: isPlaneEnabled("graph")
        ? `url set (${graphUrl})${health?.backend ? ` · backend ${health.backend}` : ""}`
        : !graphUrl
          ? "off · url not set (empty URL = plane not deployed)"
          : "off · disabled by flag (VITE_HUNT_ENABLED)",
    },
    {
      name: "Advise (investigation agent)",
      on: isPlaneEnabled("advise"),
      reason: adviseUrl ? `url set (${adviseUrl})` : "off · url not set (BYO LLM plane)",
    },
    {
      name: "Signals (feature/ML/calibration)",
      on: isPlaneEnabled("signals"),
      reason: signalsUrl ? `url set (${signalsUrl})` : "off · url not set",
    },
    {
      name: "Enforcement webhook",
      on: Boolean(envRaw("VITE_ENFORCEMENT_WEBHOOK_URL")),
      reason: envRaw("VITE_ENFORCEMENT_WEBHOOK_URL")
        ? "url set - decision outcomes delivered"
        : "off · URL not set (empty URL = plane not deployed)",
    },
    {
      name: "Queue seam",
      on: isPlaneEnabled("signals"),
      reason: isPlaneEnabled("signals")
        ? "connectors only - seam status is on /ops"
        : "off · url not set",
    },
  ];

  return (
    <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 space-y-3" data-testid="provision-glass">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Provision report card
        </h3>
        <span className="text-[10px] text-gray-500 font-mono">desk profile: {deskProfile}</span>
      </div>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.name} data-testid={`plane-row-${r.name}`} className="flex items-start justify-between gap-4 text-xs">
            <div className="flex items-center gap-2 min-w-0">
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${r.on ? "bg-green-500" : "bg-gray-600"}`}
                aria-hidden
              />
              <span className="text-gray-200">{r.name}</span>
            </div>
            <span className={`text-[10px] font-mono ${r.on ? "text-green-400" : "text-gray-500"} text-right`}>
              {r.reason}
            </span>
          </div>
        ))}
      </div>
      {health && (
        <div className="pt-2 border-t border-surface-700 text-[10px] font-mono text-gray-500">
          graph health: {health.status ?? "?"}
          {health.experience_tier ? ` · tier ${health.experience_tier}` : ""}
          {health.degrade_reason ? ` · ${health.degrade_reason}` : ""}
        </div>
      )}
      <p className="text-[10px] text-gray-600">
        Empty URL = plane honestly off. Turning a plane on is a provision + rebuild step, not a
        toggle on this page.
      </p>
    </div>
  );
}
