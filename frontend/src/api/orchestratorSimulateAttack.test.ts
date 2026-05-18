import { describe, expect, it, vi } from "vitest";

import { postOrchestratorSimulateAttack } from "./orchestratorSimulateAttack";

vi.mock("./mockData", () => ({
  getMockResponse: vi.fn(() => null),
}));

describe("postOrchestratorSimulateAttack", () => {
  it("rejects JSON when total does not match results length", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ total: 3, results: [{ transaction_id: "a" }, { transaction_id: "b" }] }),
      }),
    );
    await expect(postOrchestratorSimulateAttack("http://test/sim")).rejects.toThrow(/Incomplete simulation/);
    vi.unstubAllGlobals();
  });
});
