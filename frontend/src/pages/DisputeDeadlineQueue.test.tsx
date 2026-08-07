import type { ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as disputesApi from "@/api/v1/disputes";
import { TenantEnvironmentProvider } from "../context/TenantEnvironmentContext";
import DisputeDeadlineQueue from "./DisputeDeadlineQueue";

function wrap(ui: ReactElement) {
  return (
    <MemoryRouter>
      <TenantEnvironmentProvider>{ui}</TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

vi.mock("@/api/v1/disputes", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/v1/disputes")>();
  return {
    ...actual,
    disputes: {
      ...actual.disputes,
      deadlineQueue: vi.fn(),
      reprocessExternal: vi.fn(),
    },
  };
});

describe("DisputeDeadlineQueue", () => {
  beforeEach(() => {
    vi.mocked(disputesApi.disputes.deadlineQueue).mockResolvedValue({
      schema: "tarka.dispute_deadline_queue/v1",
      tenant_id: "demo",
      generated_at: new Date().toISOString(),
      items: [
        {
          dispute_id: "d-breach",
          tenant_id: "demo",
          status: "filed",
          dispute_type: "chargeback",
          filed_at: new Date().toISOString(),
          provider_response_deadline_at: new Date(Date.now() - 60_000).toISOString(),
          seconds_remaining: 0,
          alert_state: "breached",
          suggested_alert_hooks: [],
          external_reprocess_count: 0,
          last_external_reprocess_at: null,
        },
        {
          dispute_id: "d-near",
          tenant_id: "demo",
          status: "investigating",
          dispute_type: "chargeback",
          filed_at: new Date().toISOString(),
          provider_response_deadline_at: new Date(Date.now() + 3_600_000).toISOString(),
          seconds_remaining: 1800,
          alert_state: "near_breach",
          suggested_alert_hooks: [],
          external_reprocess_count: 1,
          last_external_reprocess_at: null,
        },
      ],
    });
  });

  it("shows breached badge and reprocess actions for alert rows", async () => {
    render(wrap(<DisputeDeadlineQueue />));

    await waitFor(() => {
      expect(screen.getByTestId("dispute-deadline-queue")).toBeInTheDocument();
    });

    expect(screen.getByTestId("alert-d-breach")).toHaveTextContent("breached");
    expect(screen.getByTestId("reprocess-d-breach")).toBeInTheDocument();
    expect(screen.getByTestId("reprocess-d-near")).toBeInTheDocument();
  });
});
