import { useEffect, type ReactNode } from "react";

import { MicroDevFirstRunWizard } from "@/components/MicroDevFirstRunWizard";
import { INCLUDE_DEMO_SURFACE } from "@/config/leanNav";
import { useMicroDevOnboardingStore } from "@/state/microDevOnboardingStore";
import { useRuntimeEnvironmentStore } from "@/state/runtimeEnvironmentStore";

export function MicroDevOnboardingGate({ children }: { children: ReactNode }) {
  const tier = useRuntimeEnvironmentStore((s) => s.tier);
  const phase = useMicroDevOnboardingStore((s) => s.phase);
  const bootstrap = useMicroDevOnboardingStore((s) => s.bootstrap);

  useEffect(() => {
    if (!INCLUDE_DEMO_SURFACE) return;
    void bootstrap(tier);
  }, [tier, bootstrap]);

  // Brochure-only SQLite wizard. Product and demo are Postgres lite — a proxy
  // blip must not replace the desk with the first-run wizard.
  if (!INCLUDE_DEMO_SURFACE || tier !== "micro") {
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
