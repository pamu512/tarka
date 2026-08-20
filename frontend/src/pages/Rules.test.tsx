import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { TenantEnvironmentProvider } from "@/context/TenantEnvironmentContext";
import Rules from "@/pages/Rules";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    rules: {
      ...actual.rules,
      list: vi.fn(),
      changeLog: vi.fn(),
      telemetry: vi.fn(),
      verticalPacks: vi.fn(),
    },
  };
});

function wrap(ui: ReactElement, path = "/rules?pack=shadow_payment_probe_v1.json") {
  return (
    <MemoryRouter initialEntries={[path]}>
      <TenantEnvironmentProvider>
        <Routes>
          <Route path="/rules" element={ui} />
        </Routes>
      </TenantEnvironmentProvider>
    </MemoryRouter>
  );
}

const SHADOW_PACK = {
  _file: "shadow_payment_probe_v1.json",
  name: "shadow_payment_probe_v1",
  version: 1,
  rules: [
    {
      id: "probe_1",
      description: "Shadow payment probe",
      score_delta: 10,
      tags: ["shadow"],
      when: [{ field: "amount", op: "gte", value: 100 }],
      enabled: true,
    },
  ],
  tag_rules: [],
};

describe("Rules workspace tabs", () => {
  beforeEach(() => {
    vi.mocked(client.rules.list).mockReset();
    vi.mocked(client.rules.changeLog).mockReset();
    vi.mocked(client.rules.telemetry).mockReset();
    vi.mocked(client.rules.verticalPacks).mockReset();

    vi.mocked(client.rules.list).mockResolvedValue({ packs: [SHADOW_PACK] });
    vi.mocked(client.rules.verticalPacks).mockResolvedValue({ vertical_packs: {} });
    vi.mocked(client.rules.telemetry).mockResolvedValue({
      since_unix: 1_700_000_000,
      total_hits: 17,
      unique_keys: 2,
      rows: [
        { pack_file: "shadow_payment_probe_v1.json", rule_id: "probe_1", kind: "json", hits: 12 },
        { pack_file: "scout_canvas_hash.json", rule_id: "scout", kind: "json", hits: 5 },
      ],
    });
    vi.mocked(client.rules.changeLog).mockResolvedValue({
      items: [
        {
          ts: "2026-08-20T12:04:00Z",
          action: "create_scout_pack",
          file: "scout_canvas_hash.json",
          actor: "anoop",
        },
      ],
    });
  });

  it("defaults to the pack builder and keeps telemetry/changelog one click away", async () => {
    render(wrap(<Rules />));

    expect(await screen.findByRole("heading", { name: "shadow_payment_probe_v1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Add Rule" })).toBeInTheDocument();

    const builderTab = screen.getByRole("tab", { name: /^Builder$/i });
    expect(builderTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Hit telemetry/i })).toHaveTextContent("17");
    expect(screen.getByRole("tab", { name: /Recent changes/i })).toBeInTheDocument();

    expect(screen.queryByText(/since API process start/i)).not.toBeInTheDocument();
    expect(screen.queryByText("create_scout_pack")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Hit telemetry/i }));
    expect(screen.getByText(/since API process start/i)).toBeInTheDocument();
    expect(screen.getByText(/probe_1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+ Add Rule" })).not.toBeInTheDocument();
    expect(screen.queryByText("create_scout_pack")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Recent changes/i }));
    expect(screen.getByText("create_scout_pack")).toBeInTheDocument();
    expect(screen.getByText("scout_canvas_hash.json")).toBeInTheDocument();
    expect(screen.queryByText(/since API process start/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /^Builder$/i }));
    expect(screen.getByRole("button", { name: "+ Add Rule" })).toBeInTheDocument();
    expect(screen.queryByText(/since API process start/i)).not.toBeInTheDocument();
    expect(screen.queryByText("create_scout_pack")).not.toBeInTheDocument();
  });

  it("still exposes empty telemetry and changelog tabs when APIs return nothing", async () => {
    vi.mocked(client.rules.telemetry).mockResolvedValue({
      since_unix: 0,
      total_hits: 0,
      unique_keys: 0,
      rows: [],
    });
    vi.mocked(client.rules.changeLog).mockResolvedValue({ items: [] });

    render(wrap(<Rules />));

    await waitFor(() => expect(screen.getByRole("heading", { name: "shadow_payment_probe_v1" })).toBeInTheDocument());
    expect(screen.queryByText(/since API process start/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Hit telemetry/i }));
    expect(screen.getByText(/No rule hits recorded yet/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Recent changes/i }));
    expect(screen.getByText(/No pack changes recorded yet/i)).toBeInTheDocument();
  });
});
