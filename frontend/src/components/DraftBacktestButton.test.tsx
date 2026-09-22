import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { DraftBacktestButton } from "./DraftBacktestButton";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    backtestJobs: {
      ...actual.backtestJobs,
      enqueue: vi.fn(),
    },
  };
});

const PACK = {
  version: 1,
  name: "velocity_draft",
  rules: [{ id: "r1", when: { field: "amount", op: "gte", value: 100 } }],
  tag_rules: [],
};

function enqueueResponse(overrides: Partial<client.BacktestJobEnqueueResponse> = {}) {
  return { job_id: "job-123", status: "PENDING", ...overrides } as client.BacktestJobEnqueueResponse;
}

describe("DraftBacktestButton", () => {
  beforeEach(() => {
    vi.mocked(client.backtestJobs.enqueue).mockReset();
  });

  it("enqueues a 7-day window job with the draft pack and shows the job link", async () => {
    vi.mocked(client.backtestJobs.enqueue).mockResolvedValue(enqueueResponse());
    render(<DraftBacktestButton pack={PACK} tenantId="acme" />);
    fireEvent.click(screen.getByRole("button", { name: /backtest draft/i }));
    await waitFor(() => {
      expect(client.backtestJobs.enqueue).toHaveBeenCalledTimes(1);
    });
    const body = vi.mocked(client.backtestJobs.enqueue).mock.calls[0][0];
    expect(body.tenant_id).toBe("acme");
    expect(body.rule_pack).toMatchObject({ name: "velocity_draft", version: 1 });
    // 7-day window: start < end, end ~ now, gap <= 7d + clock skew
    const start = new Date(body.start_time as string).getTime();
    const end = new Date(body.end_time as string).getTime();
    const days = (end - start) / 86_400_000;
    expect(days).toBeGreaterThan(6.9);
    expect(days).toBeLessThanOrEqual(7.1);
    expect(body.rule_pack).not.toHaveProperty("_file");
    const link = await screen.findByRole("link", { name: /job-123/i });
    expect(link.getAttribute("href")).toContain("/ops/backtest");
    expect(link.getAttribute("href")).toContain("job_id=job-123");
  });

  it("keeps window at 7d when end_time lands a tick after enqueue", async () => {
    vi.mocked(client.backtestJobs.enqueue).mockImplementation(async () => {
      await new Promise((r) => setTimeout(r, 30));
      return enqueueResponse();
    });
    render(<DraftBacktestButton pack={PACK} tenantId="acme" />);
    fireEvent.click(screen.getByRole("button", { name: /backtest draft/i }));
    await waitFor(() => {
      expect(client.backtestJobs.enqueue).toHaveBeenCalled();
    });
    const body = vi.mocked(client.backtestJobs.enqueue).mock.calls[0][0];
    const days =
      (new Date(body.end_time as string).getTime() -
        new Date(body.start_time as string).getTime()) /
      86_400_000;
    expect(days).toBeLessThanOrEqual(7.1);
  });

  it("surfaces an honest error, no link, when enqueue rejects", async () => {
    vi.mocked(client.backtestJobs.enqueue).mockRejectedValue(
      new Error("analytics engine not configured"),
    );
    render(<DraftBacktestButton pack={PACK} tenantId="acme" />);
    fireEvent.click(screen.getByRole("button", { name: /backtest draft/i }));
    await screen.findByText(/analytics engine not configured/i);
    expect(screen.queryByRole("link", { name: /job-/i })).toBeNull();
  });

  it("disables while a job is in flight", async () => {
    let resolveEnqueue: (v: client.BacktestJobEnqueueResponse) => void = () => {};
    vi.mocked(client.backtestJobs.enqueue).mockImplementation(
      () =>
        new Promise((res) => {
          resolveEnqueue = res;
        }),
    );
    render(<DraftBacktestButton pack={PACK} tenantId="acme" />);
    const btn = screen.getByRole("button", { name: /backtest draft/i });
    fireEvent.click(btn);
    expect(screen.getByRole("button", { name: /backtesting…/i })).toBeDisabled();
    resolveEnqueue(enqueueResponse());
    await screen.findByRole("link", { name: /job-123/i });
  });
});
