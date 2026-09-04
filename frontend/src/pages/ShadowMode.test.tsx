import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import ShadowMode from "@/pages/ShadowMode";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    rules: {
      ...actual.rules,
      list: vi.fn(),
    },
    shadow: {
      ...actual.shadow,
      stats: vi.fn(),
      observations: vi.fn(),
      setPackMode: vi.fn(),
    },
  };
});

function wrap(ui: ReactElement, path = "/shadow") {
  return (
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/shadow" element={ui} />
      </Routes>
    </MemoryRouter>
  );
}

const SHADOW_PACK = {
  _file: "shadow_payment_probe_v1.json",
  name: "shadow_payment_probe_v1",
  version: 1,
  mode: "shadow" as const,
  rules: [],
  tag_rules: [],
};

describe("Observe pack modes", () => {
  beforeEach(() => {
    vi.mocked(client.rules.list).mockReset();
    vi.mocked(client.shadow.stats).mockReset();
    vi.mocked(client.shadow.observations).mockReset();
    vi.mocked(client.shadow.setPackMode).mockReset();

    vi.mocked(client.rules.list).mockResolvedValue({ packs: [SHADOW_PACK] });
    vi.mocked(client.shadow.stats).mockResolvedValue({ total: 0 });
    vi.mocked(client.shadow.observations).mockResolvedValue({ observations: [] });
    vi.mocked(client.shadow.setPackMode).mockImplementation(async () => {
      vi.mocked(client.rules.list).mockResolvedValue({
        packs: [{ ...SHADOW_PACK, mode: "active" }],
      });
      return { file: SHADOW_PACK._file, mode: "active" };
    });
  });

  it("lists shadow packs and promotes via setPackMode", async () => {
    render(wrap(<ShadowMode />));

    expect(await screen.findByText("shadow_payment_probe_v1.json")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Promote to Active" }));

    await waitFor(() => {
      expect(client.shadow.setPackMode).toHaveBeenCalledWith(
        "shadow_payment_probe_v1.json",
        "active",
      );
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Promote to Active" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Active" })).toBeDisabled();
  });
});
