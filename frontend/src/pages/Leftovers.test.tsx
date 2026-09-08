import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { TenantEnvironmentProvider } from "@/context/TenantEnvironmentContext";
import Leftovers from "@/pages/Leftovers";

function HuntProbe() {
  const { search } = useLocation();
  return <div>hunt {search}</div>;
}

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    cases: {
      ...actual.cases,
      listLeftovers: vi.fn(),
      claimLeftover: vi.fn(),
    },
    rules: {
      ...actual.rules,
      createL2Draft: vi.fn(),
    },
    decisions: {
      ...actual.decisions,
      queueSeam: vi.fn(),
    },
  };
});

function wrap(ui: ReactElement, path = "/leftovers") {
  return (
    <MemoryRouter initialEntries={[path]}>
      <TenantEnvironmentProvider>
        <Routes>
          <Route path="/leftovers" element={ui} />
          <Route path="/graph" element={<HuntProbe />} />
        </Routes>
      </TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

const freeRow = {
  leftover_id: "c-free",
  entity_id: "buyer-1",
  origin: "hold" as const,
  last_outcome: null,
  last_act: "held" as const,
  claimed_by: null,
  sla_breached: false,
  trace_id: "tr-1",
  brief: "Pack device_signals — hits sdk_bot",
  pack_id: "device_signals",
  rule_hits: ["event_count_1h", "sdk_bot"],
};

const takenRow = {
  leftover_id: "c-taken",
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
    vi.mocked(client.decisions.queueSeam).mockReset();
    vi.mocked(client.cases.listLeftovers).mockResolvedValue({ leftovers: [freeRow, takenRow], truncated: false });
    vi.mocked(client.cases.claimLeftover).mockResolvedValue(freeRow);
    vi.mocked(client.decisions.queueSeam).mockResolvedValue({ connected: false });
  });

  it("claims a free row then opens Hunt", async () => {
    render(wrap(<Leftovers />));
    const row = await screen.findByRole("button", { name: /work buyer-1/i });
    fireEvent.click(row);
    await waitFor(() => {
      expect(client.cases.claimLeftover).toHaveBeenCalledWith("c-free", "demo");
    });
    const hunt = await screen.findByText(/hunt/);
    expect(hunt).toBeInTheDocument();
    const q = new URLSearchParams(hunt.textContent?.replace(/^hunt\s*/, "") ?? "");
    expect(q.get("leftover_id")).toBe("c-free");
    expect(q.get("pack")).toBe("device_signals");
    expect(q.get("hits")).toBe("event_count_1h,sdk_bot");
    expect(q.get("entity_id")).toBe("buyer-1");
    expect(q.get("decision_id")).toBe("dec:tr-1");
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

  it("offers Create draft and Author via BYO on leftover rows", async () => {
    render(wrap(<Leftovers />));
    expect((await screen.findAllByRole("button", { name: /create draft/i })).length).toBeGreaterThan(0);
    expect((await screen.findAllByRole("button", { name: /author via byo/i })).length).toBeGreaterThan(0);
  });

  it("does not treat leftover brief as override why; Create draft stays disabled until a typed why", async () => {
    vi.mocked(client.rules.createL2Draft).mockReset();
    vi.mocked(client.rules.createL2Draft).mockResolvedValue({
      file: "l2.json",
      pack: { mode: "shadow" },
    });
    render(wrap(<Leftovers />));
    const create = (await screen.findAllByRole("button", { name: /create draft/i }))[0];
    expect(create).toBeDisabled();
    fireEvent.click(create);
    expect(client.rules.createL2Draft).not.toHaveBeenCalled();
    const why = screen.getAllByTestId("leftover-override-why")[0];
    fireEvent.change(why, { target: { value: "human leftover why" } });
    expect(create).toBeEnabled();
    fireEvent.click(create);
    await waitFor(() => {
      expect(client.rules.createL2Draft).toHaveBeenCalledWith(
        expect.objectContaining({
          leftover_id: "c-free",
          override_why: "human leftover why",
        }),
        "demo",
      );
    });
    expect(client.rules.createL2Draft).toHaveBeenCalledWith(
      expect.not.objectContaining({ override_why: freeRow.brief }),
      "demo",
    );
  });

  it("says leftovers are not a case CRM when queue is off", async () => {
    vi.mocked(client.cases.listLeftovers).mockResolvedValue({ leftovers: [], truncated: false });
    render(wrap(<Leftovers />));
    expect(await screen.findByTestId("queue-honesty")).toHaveTextContent(/not your case CRM/i);
  });

  it("shows leftover brief or em dash", async () => {
    render(wrap(<Leftovers />));
    const cells = await screen.findAllByTestId("leftover-brief");
    expect(cells).toHaveLength(2);
    expect(cells[0]).toHaveTextContent("Pack device_signals — hits sdk_bot");
    expect(cells[1]).toHaveTextContent("—");
  });
});
