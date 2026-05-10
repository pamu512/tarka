import { render, screen, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TransactionTicker } from "./TransactionTicker";

const { recentAudit } = vi.hoisted(() => ({
  recentAudit: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    decisions: {
      ...actual.decisions,
      recentAudit,
    },
  };
});

describe("TransactionTicker", () => {
  afterEach(() => {
    recentAudit.mockReset();
    vi.useRealTimers();
  });

  it("renders audit-first columns from GET /v1/audit/recent", async () => {
    recentAudit.mockResolvedValue({
      tenant_id: "t1",
      items: [
        {
          trace_id: "00000000-0000-4000-8000-000000000001",
          short_id: "00000000",
          amount: 42.5,
          currency: "USD",
          rule_result: "SHADOW_REVIEW",
          ai_confidence: 0.72,
          created_at: "2026-01-01T00:00:00.000Z",
        },
      ],
    });

    render(<TransactionTicker tenantId="t1" pollIntervalMs={60_000} limit={20} />);

    expect(await screen.findByText("00000000")).toBeInTheDocument();
    expect(screen.getByText("SHADOW_REVIEW")).toBeInTheDocument();
    expect(screen.getByText("72%")).toBeInTheDocument();
  });

  it("gate: 20 burst updates in 1s without throwing (startTransition + layout)", () => {
    vi.useFakeTimers();
    recentAudit.mockResolvedValue({ tenant_id: "t1", items: [] });

    render(<TransactionTicker tenantId="t1" stressBurst pollIntervalMs={60_000} />);

    for (let i = 0; i < 20; i++) {
      act(() => {
        vi.advanceTimersByTime(50);
      });
    }

    expect(screen.getAllByText("SHADOW_REVIEW").length).toBeGreaterThan(0);
  });
});
