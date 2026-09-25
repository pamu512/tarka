import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { ArenaPanel } from "./ArenaPanel";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    decisions: {
      ...actual.decisions,
      arenaReport: vi.fn(),
      arenaConfig: vi.fn(),
    },
  };
});

describe("ArenaPanel", () => {
  beforeEach(() => {
    vi.mocked(client.decisions.arenaReport).mockReset();
    vi.mocked(client.decisions.arenaConfig).mockReset();
  });

  it("renders the weekly champion report with honest nulls for unknown labels", async () => {
    vi.mocked(client.decisions.arenaReport).mockResolvedValue({
      schema_id: "tarka.challenger_report/v1",
      tenant_id: "acme",
      n: 120,
      challengers: {
        challenger_a: { n: 120, divergence_rate: 0.25, fp_delta: null },
        challenger_b: { n: 120, divergence_rate: 0.1, fp_delta: -0.02 },
      },
    });
    vi.mocked(client.decisions.arenaConfig).mockResolvedValue({
      configured: true,
      challengers: { challenger_a: {}, challenger_b: {} },
    });
    render(<ArenaPanel tenantId="acme" />);
    expect(await screen.findByText("challenger_a")).toBeTruthy();
    expect(screen.getByText("25.0%")).toBeTruthy();
    expect(screen.getAllByText("— unknown").length).toBeGreaterThanOrEqual(1); // fp_delta null
    expect(screen.getByText("-2.0pp")).toBeTruthy();
    expect(screen.getByText(/2 challengers wired/)).toBeTruthy();
  });

  it("shows unconfigured state when no challengers are wired", async () => {
    vi.mocked(client.decisions.arenaReport).mockResolvedValue({
      schema_id: "tarka.challenger_report/v1",
      tenant_id: "acme",
      n: 0,
      challengers: {},
    });
    vi.mocked(client.decisions.arenaConfig).mockResolvedValue({
      configured: false,
      challengers: {},
    });
    render(<ArenaPanel tenantId="acme" />);
    expect(
      await screen.findByText(/no challengers wired \(admin PUT \/v1\/ops\/arena\/config\)/),
    ).toBeTruthy();
    expect(screen.getByText(/No shadow records yet/)).toBeTruthy();
  });

  it("surfaces fetch errors honestly", async () => {
    vi.mocked(client.decisions.arenaReport).mockRejectedValue(new Error("arena down"));
    vi.mocked(client.decisions.arenaConfig).mockRejectedValue(new Error("arena down"));
    render(<ArenaPanel tenantId="acme" />);
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("arena down");
    });
  });

  it("refresh refetches the report", async () => {
    vi.mocked(client.decisions.arenaReport).mockResolvedValue({
      schema_id: "tarka.challenger_report/v1",
      tenant_id: "acme",
      n: 1,
      challengers: { c1: { n: 1, divergence_rate: 0, fp_delta: 0 } },
    });
    vi.mocked(client.decisions.arenaConfig).mockResolvedValue({
      configured: true,
      challengers: { c1: {} },
    });
    render(<ArenaPanel tenantId="acme" />);
    await screen.findByText("c1");
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => {
      expect(client.decisions.arenaReport).toHaveBeenCalledTimes(2);
    });
  });
});
