import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/api/client";
import { ObserveEasePanel } from "./ObserveEasePanel";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    decisions: {
      ...actual.decisions,
      byomStatus: vi.fn(),
    },
    rules: {
      ...actual.rules,
      list: vi.fn(),
      proposeDemote: vi.fn(),
      confirmDemote: vi.fn(),
    },
    shadow: {
      ...actual.shadow,
      setPackMode: vi.fn(),
    },
  };
});

function wrap(ui: ReactElement) {
  return <MemoryRouter>{ui}</MemoryRouter>;
}

describe("ObserveEasePanel", () => {
  beforeEach(() => {
    vi.mocked(client.decisions.byomStatus).mockReset();
    vi.mocked(client.shadow.setPackMode).mockReset();
    vi.mocked(client.rules.list).mockReset();
    vi.mocked(client.rules.proposeDemote).mockReset();
    vi.mocked(client.rules.confirmDemote).mockReset();
    vi.mocked(client.decisions.byomStatus).mockResolvedValue({
      connected: false,
      backend: "",
      model: "",
    });
    vi.mocked(client.shadow.setPackMode).mockResolvedValue({
      file: "draft_a.json",
      mode: "shadow",
    });
    vi.mocked(client.rules.list).mockResolvedValue({
      packs: [
        {
          _file: "live_a.json",
          name: "live_a",
          version: 1,
          mode: "active",
          rules: [],
          tag_rules: [],
        },
      ],
    });
    vi.mocked(client.rules.proposeDemote).mockResolvedValue({
      file: "live_a.json",
      mode: "active",
      demote: { state: "proposed", proposed_by: "ops-lead" },
    });
    vi.mocked(client.rules.confirmDemote).mockResolvedValue({
      file: "live_a.json",
      mode: "shadow",
      demote: { state: "confirmed" },
    });
  });

  it("Propose Demote parks; Confirm stays off until proposed; no silent PUT", async () => {
    render(
      wrap(
        <ObserveEasePanel
          tenantId="demo"
          drafts={[{ name: "draft_a", file: "draft_a.json" }]}
          promoteAllowed={false}
          blockers={[]}
          slipRules={[]}
          selectedDraft="draft_a"
          onSelectDraft={() => {}}
          onPromote={() => {}}
          canPromote={false}
        />,
      ),
    );

    expect(screen.queryByRole("button", { name: /human demote/i })).toBeNull();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /propose demote/i })).toBeTruthy();
    });
    expect((screen.getByRole("button", { name: /confirm demote/i }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/scout does not auto-demote/i)).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/demote reason/i), {
      target: { value: "fp burst on live pack" },
    });
    fireEvent.click(screen.getByRole("button", { name: /propose demote/i }));
    await waitFor(() => {
      expect(client.rules.proposeDemote).toHaveBeenCalledWith(
        "live_a.json",
        "fp burst on live pack",
        "demo",
      );
    });
    expect(client.shadow.setPackMode).not.toHaveBeenCalled();
  });

  it("Confirm demote is a separate human action after propose", async () => {
    vi.mocked(client.rules.list).mockResolvedValue({
      packs: [
        {
          _file: "live_a.json",
          name: "live_a",
          version: 1,
          mode: "active",
          rules: [],
          tag_rules: [],
          lifecycle: { demote: { state: "proposed", proposed_by: "ops-lead" } },
        },
      ],
    });

    render(
      wrap(
        <ObserveEasePanel
          tenantId="demo"
          drafts={[{ name: "draft_a", file: "draft_a.json" }]}
          promoteAllowed={false}
          blockers={[]}
          slipRules={[]}
          selectedDraft="draft_a"
          onSelectDraft={() => {}}
          onPromote={() => {}}
          canPromote={false}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText(/demote reason/i), {
      target: { value: "human confirm retire" },
    });
    await waitFor(() => {
      expect((screen.getByRole("button", { name: /confirm demote/i }) as HTMLButtonElement).disabled).toBe(false);
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm demote/i }));
    await waitFor(() => {
      expect(client.rules.confirmDemote).toHaveBeenCalledWith("live_a.json", "human confirm retire");
    });
    expect(client.shadow.setPackMode).not.toHaveBeenCalled();
  });

  it("successor copy says human owns Promote", async () => {
    render(
      wrap(
        <ObserveEasePanel
          tenantId="demo"
          drafts={[{ name: "byo_succ", file: "byo_succ.json", is_ai_authored: true }]}
          promoteAllowed={false}
          blockers={[]}
          slipRules={[
            {
              rule_id: "r1",
              hypothesis: "successor",
              parked_draft: "byo_succ",
            },
          ]}
          selectedDraft="byo_succ"
          onSelectDraft={() => {}}
          onPromote={() => {}}
          canPromote={false}
        />,
      ),
    );

    await waitFor(() => {
      expect(screen.getByText(/model suggested successor — you own Promote/i)).toBeTruthy();
    });
  });
});
