import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("MicroDevOnboardingGate", () => {
  it("product profile renders children and never shows the micro-dev status spinner", async () => {
    vi.stubEnv("VITE_DESK_PROFILE", "product");
    vi.resetModules();

    const { useRuntimeEnvironmentStore } = await import("@/state/runtimeEnvironmentStore");
    const { useMicroDevOnboardingStore } = await import("@/state/microDevOnboardingStore");
    useRuntimeEnvironmentStore.setState({ tier: "micro" });
    useMicroDevOnboardingStore.setState({ phase: "idle" });

    const { MicroDevOnboardingGate } = await import("./MicroDevOnboardingGate");
    render(
      <MicroDevOnboardingGate>
        <div>desk-children</div>
      </MicroDevOnboardingGate>,
    );

    expect(screen.getByText("desk-children")).toBeInTheDocument();
    expect(screen.queryByText("Checking micro-dev onboarding status…")).not.toBeInTheDocument();
  });
});
