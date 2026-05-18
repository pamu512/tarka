import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/context/ToastContext";

import { ControlPanel } from "./ControlPanel";

const { postOrchestratorSimulateAttack } = vi.hoisted(() => ({
  postOrchestratorSimulateAttack: vi.fn(),
}));

vi.mock("@/api/orchestratorSimulateAttack", () => ({
  postOrchestratorSimulateAttack,
}));

describe("ControlPanel", () => {
  it("gate: button stays disabled until simulate_attack resolves with full results", async () => {
    let resolveSim!: (v: { results: unknown[]; raw: unknown }) => void;
    const simPromise = new Promise<{ results: unknown[]; raw: unknown }>((r) => {
      resolveSim = r;
    });
    postOrchestratorSimulateAttack.mockReturnValue(simPromise);

    render(
      <ToastProvider>
        <ControlPanel />
      </ToastProvider>,
    );

    const btn = screen.getByRole("button", { name: "Trigger Simulation" });
    expect(btn).not.toBeDisabled();

    fireEvent.click(btn);
    expect(btn).toBeDisabled();
    expect(screen.getByLabelText(/live attack in progress/i)).toBeInTheDocument();

    resolveSim!({
      results: [{ transaction_id: "t1" }, { transaction_id: "t2" }],
      raw: { total: 2, results: [{ transaction_id: "t1" }, { transaction_id: "t2" }] },
    });

    await waitFor(() => expect(btn).not.toBeDisabled());
    expect(screen.queryByLabelText(/live attack in progress/i)).not.toBeInTheDocument();
  });
});
