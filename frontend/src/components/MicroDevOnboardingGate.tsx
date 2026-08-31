import { useEffect, type ReactNode } from "react";

import { MicroDevFirstRunWizard } from "@/components/MicroDevFirstRunWizard";
import { LEAN_NAV } from "@/config/leanNav";
import { useMicroDevOnboardingStore } from "@/state/microDevOnboardingStore";
import { useRuntimeEnvironmentStore } from "@/state/runtimeEnvironmentStore";

export function MicroDevOnboardingGate({ children }: { children: ReactNode }) {
  const tier = useRuntimeEnvironmentStore((s) => s.tier);
  const phase = useMicroDevOnboardingStore((s) => s.phase);
  const bootstrap = useMicroDevOnboardingStore((s) => s.bootstrap);

  useEffect(() => {
    if (LEAN_NAV) return;
    void bootstrap(tier);
  }, [tier, bootstrap]);

  // Evaluate-only desk is Postgres lite, not micro-dev. A proxy blip must not
  // replace Cases / Decisions with the SQLite first-run wizard.
  if (LEAN_NAV || tier !== "micro") {
    return <>{children}</>;
  }

  if (phase === "dashboard") {
    return <>{children}</>;
  }

  if (phase === "loading" || phase === "idle") {
    return (
      <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-surface-950 text-gray-300">
        <div className="h-10 w-10 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
        <p className="mt-4 text-sm">Checking micro-dev onboarding status…</p>
      </div>
    );
  }

  return <MicroDevFirstRunWizard />;
}
