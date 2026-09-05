import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { TenantEnvironmentProvider } from "@/context/TenantEnvironmentContext";
import Leftovers from "@/pages/Leftovers";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    cases: {
      ...actual.cases,
      listLeftovers: vi.fn(),
      claimLeftover: vi.fn(),
    },
  };
});

function wrap(ui: ReactElement, path = "/leftovers") {
  return (
    <MemoryRouter initialEntries={[path]}>
      <TenantEnvironmentProvider>
        <Routes>
          <Route path="/leftovers" element={ui} />
          <Route path="/graph" element={<div>hunt</div>} />
        </Routes>
      </TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

const freeRow = {
  case_id: "c-free",
  entity_id: "buyer-1",
  origin: "hold" as const,
  last_outcome: null,
  last_act: "held" as const,
  claimed_by: null,
  sla_breached: false,
  trace_id: "tr-1",
};

const takenRow = {
  case_id: "c-taken",
  entity_id: "buyer-2",
  origin: "evaluate" as const,
  last_outcome: "deny" as const,
  last_act: "held" as const,
  claimed_by: "ana-b",
  sla_breached: false,
  trace_id: "tr-2",
};

describe("Leftovers", () => {
  beforeEach(() => {
    vi.mocked(client.cases.listLeftovers).mockReset();
    vi.mocked(client.cases.claimLeftover).mockReset();
    vi.mocked(client.cases.listLeftovers).mockResolvedValue({ leftovers: [freeRow, takenRow], truncated: false });
    vi.mocked(client.cases.claimLeftover).mockResolvedValue(freeRow);
  });

  it("claims a free row then opens Hunt", async () => {
    render(wrap(<Leftovers />));
    const row = await screen.findByRole("button", { name: /work buyer-1/i });
    fireEvent.click(row);
    await waitFor(() => {
      expect(client.cases.claimLeftover).toHaveBeenCalledWith("c-free", "demo");
    });
    expect(await screen.findByText("hunt")).toBeInTheDocument();
  });

  it("fail-closes when leftovers API is down", async () => {
    vi.mocked(client.cases.listLeftovers).mockRejectedValue(new Error("down"));
    render(wrap(<Leftovers />));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /work buyer-1/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/no leftovers/i)).not.toBeInTheDocument();
  });

  it("does not claim a row owned by someone else", async () => {
    render(wrap(<Leftovers />));
    await screen.findByText("ana-b");
    expect(screen.queryByRole("button", { name: /work buyer-2/i })).not.toBeInTheDocument();
    expect(client.cases.claimLeftover).not.toHaveBeenCalled();
  });
});
