import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { PromoteReadinessPanel } from "./PromoteReadinessPanel";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    rules: {
      ...actual.rules,
      shadowPackReadiness: vi.fn(),
    },
  };
});

const READY = {
  draft_id: "l2_x",
  tenant_id: "acme",
  ready: false,
  blockers: ["window_open"],
  desk_promote_gate: {
    promote_allowed: false,
    blockers: ["window_open"],
    metrics: { rule_hit_rate: 0.12, shadow_divergence: 0.0 },
  },
  leftover_promote_gate: { promote_allowed: true, blockers: [] },
  calibration_window: { ok: false, blockers: ["window_open"], days: 2, min_days: 7, min_labels: 50, label_count: 12 },
};

describe("PromoteReadinessPanel", () => {
  beforeEach(() => {
    vi.mocked(client.rules.shadowPackReadiness).mockReset();
  });

  it("renders gates honestly: not ready + named blockers + window numbers", async () => {
    vi.mocked(client.rules.shadowPackReadiness).mockResolvedValue(READY as never);
    render(<PromoteReadinessPanel draftId="l2_x" tenantId="acme" />);
    await screen.findByText(/not ready/i);
    expect(screen.getByText(/window_open/i)).toBeTruthy();
    expect(screen.getByText(/2\s*\/\s*7.*days|days.*2.*of.*7/i)).toBeTruthy();
    expect(screen.getByText(/12.*labels|labels.*12/i)).toBeTruthy();
  });

  it("shows ready state with no blockers", async () => {
    vi.mocked(client.rules.shadowPackReadiness).mockResolvedValue({
      ...READY,
      ready: true,
      blockers: [],
      desk_promote_gate: { promote_allowed: true, blockers: [], metrics: { rule_hit_rate: 0.4 } },
      calibration_window: { ...READY.calibration_window, ok: true, blockers: [] },
    } as never);
    render(<PromoteReadinessPanel draftId="l2_x" tenantId="acme" />);
    await screen.findByText(/ready/i);
    expect(screen.queryByText(/window_open/i)).toBeNull();
  });

  it("renders dash + reason when metrics are unknown (never 0% theater)", async () => {
    vi.mocked(client.rules.shadowPackReadiness).mockResolvedValue({
      ...READY,
      desk_promote_gate: { promote_allowed: false, blockers: [], metrics: { rule_hit_rate: null, shadow_divergence: null } },
    } as never);
    render(<PromoteReadinessPanel draftId="l2_x" tenantId="acme" />);
    await screen.findByText(/not ready|ready/i);
    expect(screen.getAllByText(/—|unknown/i).length).toBeGreaterThan(0);
  });

  it("surfaces fetch errors honestly", async () => {
    vi.mocked(client.rules.shadowPackReadiness).mockRejectedValue(new Error("gate backend down"));
    render(<PromoteReadinessPanel draftId="l2_x" tenantId="acme" />);
    await screen.findByText(/gate backend down/i);
  });

  it("re-fetches on demand", async () => {
    vi.mocked(client.rules.shadowPackReadiness).mockResolvedValue(READY as never);
    render(<PromoteReadinessPanel draftId="l2_x" tenantId="acme" />);
    await screen.findByText(/not ready/i);
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => {
      expect(client.rules.shadowPackReadiness).toHaveBeenCalledTimes(2);
    });
  });
});
