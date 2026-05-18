/** @vitest-environment jsdom */

import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TransactionTicker } from "./TransactionTicker";

const fetchMock = vi.fn();

describe("TransactionTicker", () => {
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("renders audit-first columns from GET /v1/audit/recent", async () => {
    vi.stubGlobal(
      "fetch",
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({
          items: [
            {
              timestamp: "2026-01-01T00:00:00.000Z",
              transaction_id: "00000000-0000-4000-8000-000000000001",
              amount_cents: 4250,
              status: "SHADOW_REVIEW",
              short_id: "A1B2C3D4",
              ai_confidence: 0.72,
            },
          ],
        }),
      }),
    );

    render(<TransactionTicker pollIntervalMs={60_000} limit={20} />);

    await screen.findByText("A1B2C3D4");
    expect(document.body.textContent).toContain("SHADOW_REVIEW");
    expect(document.body.textContent).toContain("72%");
    expect(document.body.textContent).toContain("$42.50");
  });

  it("gate: 20 burst updates in 1s without throwing (startTransition + layout)", () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      fetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ items: [] }),
      }),
    );

    render(<TransactionTicker stressBurst pollIntervalMs={60_000} />);

    for (let i = 0; i < 20; i++) {
      act(() => {
        vi.advanceTimersByTime(50);
      });
    }

    expect(screen.getAllByText("SHADOW_REVIEW").length).toBeGreaterThan(0);
  });
});
