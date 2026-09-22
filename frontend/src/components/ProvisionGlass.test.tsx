import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProvisionGlass } from "./ProvisionGlass";

const HEALTH_OK = { status: "ok", backend: "age", experience_tier: "full" };
const HEALTH_DOWN = { status: "degraded", backend: "age", degrade_reason: "backend_unreachable" };

describe("ProvisionGlass", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  function renderGlass(env: Record<string, string>, health = HEALTH_OK) {
    vi.doMock("import.meta.env", () => ({ ...env }));
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", env.VITE_GRAPH_SERVICE_URL ?? "");
    vi.stubEnv("VITE_INVESTIGATION_AGENT_URL", env.VITE_INVESTIGATION_AGENT_URL ?? "");
    vi.stubEnv("VITE_SIGNAL_API_URL", env.VITE_SIGNAL_API_URL ?? "");
    vi.stubEnv("VITE_HUNT_ENABLED", env.VITE_HUNT_ENABLED ?? "");
    return render(<ProvisionGlass health={health} deskProfile={env.DESK_PROFILE ?? "product"} />);
  }

  it("lists every plane with on/off state and the reason", () => {
    renderGlass({
      VITE_GRAPH_SERVICE_URL: "http://graph:8001",
      VITE_INVESTIGATION_AGENT_URL: "",
      VITE_SIGNAL_API_URL: "http://signal:8004",
    });
    expect(screen.getByTestId("plane-row-Graph (Hunt)")?.textContent).toMatch(/url set/i);
    expect(screen.getByTestId("plane-row-Advise (investigation agent)")?.textContent).toMatch(/not set/i);
    expect(screen.getByTestId("plane-row-Signals (feature/ML/calibration)")?.textContent).toMatch(/url set/i);
  });

  it("explains hunt-off even when graph URL is set (explicit flag)", () => {
    renderGlass({
      VITE_GRAPH_SERVICE_URL: "http://graph:8001",
      VITE_HUNT_ENABLED: "0",
    });
    expect(screen.getByTestId("plane-row-Graph (Hunt)")?.textContent).toMatch(/disabled by flag/i);
  });

  it("shows backend health honestly when degraded", () => {
    renderGlass({ VITE_GRAPH_SERVICE_URL: "http://graph:8001" }, HEALTH_DOWN);
    expect(screen.getByText(/degraded/i)).toBeTruthy();
    expect(screen.getByText(/backend_unreachable/i)).toBeTruthy();
  });

  it("shows the desk profile", () => {
    renderGlass({}, HEALTH_OK);
    expect(screen.getByText(/product/i)).toBeTruthy();
  });
});
