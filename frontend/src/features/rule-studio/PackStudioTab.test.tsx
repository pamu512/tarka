import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { TenantEnvironmentProvider } from "@/context/TenantEnvironmentContext";
import * as client from "@/api/client";
import { ApiRequestError } from "@/api/client";
import { fallbackAuthorCatalog } from "@/domain/authorCatalogFallback";
import { usePackDraftStore } from "./store/packDraftStore";
import PackStudioTab from "./PackStudioTab";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    rules: {
      ...actual.rules,
      list: vi.fn(),
      authorCatalog: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      createScoutPack: vi.fn(),
      forceLiveRulePack: vi.fn(),
      proposeDemote: vi.fn(),
      confirmDemote: vi.fn(),
    },
  };
});

function wrap(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TenantEnvironmentProvider>{ui}</TenantEnvironmentProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const SHADOW_PACK = {
  _file: "shadow_probe.json",
  version: 1,
  name: "shadow_probe",
  mode: "shadow",
  rules: [
    {
      id: "r1",
      when: [{ field: "amount", op: "gte", value: 100 }],
      tags: ["t"],
      score_delta: 10,
      description: "d",
    },
  ],
  tag_rules: [],
  canary_percent: null,
  effective_at: null,
  approved_by: null,
};

const ACTIVE_PACK = {
  ...SHADOW_PACK,
  _file: "live_probe.json",
  name: "live_probe",
  mode: "active",
};

describe("PackStudioTab save path", () => {
  beforeEach(() => {
    usePackDraftStore.getState().reset();
    vi.mocked(client.rules.list).mockReset();
    vi.mocked(client.rules.create).mockReset();
    vi.mocked(client.rules.update).mockReset();
    vi.mocked(client.rules.authorCatalog).mockReset();
    vi.mocked(client.rules.createScoutPack).mockReset();
    vi.mocked(client.rules.list).mockResolvedValue({ packs: [SHADOW_PACK, ACTIVE_PACK] as never });
    vi.mocked(client.rules.authorCatalog).mockResolvedValue(fallbackAuthorCatalog());
    vi.mocked(client.rules.create).mockResolvedValue({
      file: "new.json",
      pack: { ...SHADOW_PACK, name: "shadow_probe_studio_2", mode: "shadow" },
    });
    vi.mocked(client.rules.update).mockResolvedValue({
      file: "shadow_probe.json",
      pack: SHADOW_PACK,
    });
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  it("save on shadow pack calls rules.update; never scout/promote/mode", async () => {
    render(wrap(<PackStudioTab />));
    await waitFor(() => expect(client.rules.list).toHaveBeenCalled());

    const select = await screen.findByLabelText("Open pack");
    fireEvent.change(select, { target: { value: "shadow_probe.json" } });

    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => {
      expect(client.rules.update).toHaveBeenCalled();
    });
    expect(client.rules.createScoutPack).not.toHaveBeenCalled();
    expect(client.rules.forceLiveRulePack).not.toHaveBeenCalled();
  });

  it("active pack disables in-place save; save-as-new-draft calls create", async () => {
    render(wrap(<PackStudioTab />));
    await waitFor(() => expect(client.rules.list).toHaveBeenCalled());

    fireEvent.change(await screen.findByLabelText("Open pack"), {
      target: { value: "live_probe.json" },
    });

    const saveBtn = screen.getByRole("button", { name: /^Save$/ });
    expect(saveBtn).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /Save as new Observe draft/i }));

    await waitFor(() => {
      expect(client.rules.create).toHaveBeenCalled();
    });
    const arg = vi.mocked(client.rules.create).mock.calls[0][0];
    expect(arg.name).toMatch(/studio/);
    expect(client.rules.update).not.toHaveBeenCalled();
  });

  it("409 on create suggests suffixed name and retries once after confirm", async () => {
    vi.mocked(client.rules.create)
      .mockRejectedValueOnce(new ApiRequestError("exists", { status: 409 }))
      .mockResolvedValueOnce({
        file: "ok.json",
        pack: { ...SHADOW_PACK, name: "studio_draft_studio_2", mode: "shadow" },
      });

    render(wrap(<PackStudioTab />));
    fireEvent.click(screen.getByRole("button", { name: /New draft/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save as new Observe draft/i }));

    await waitFor(() => {
      expect(client.rules.create).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(window.confirm)).toHaveBeenCalled();
    expect(vi.mocked(client.rules.create).mock.calls[1][0].name).toContain("studio_2");
  });
});
