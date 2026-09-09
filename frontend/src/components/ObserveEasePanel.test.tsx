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
      demoteSuggestions: vi.fn(),
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
    vi.mocked(client.decisions.demoteSuggestions).mockReset();
    vi.mocked(client.shadow.setPackMode).mockReset();
    vi.mocked(client.rules.list).mockReset();
    vi.mocked(client.rules.proposeDemote).mockReset();
    vi.mocked(client.rules.confirmDemote).mockReset();
    vi.mocked(client.decisions.byomStatus).mockResolvedValue({
      connected: false,
      backend: "",
      model: "",
    });
    vi.mocked(client.decisions.demoteSuggestions).mockResolvedValue({ suggestions: [] });
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

  it("Promote draft requires confirm; Cancel leaves Observe and does not Promote", async () => {
    const onPromote = vi.fn();
    render(
      wrap(
        <ObserveEasePanel
          tenantId="demo"
          drafts={[{ name: "draft_a", file: "draft_a.json" }]}
          promoteAllowed
          blockers={[]}
          slipRules={[]}
          selectedDraft="draft_a"
          onSelectDraft={() => {}}
          onPromote={onPromote}
          canPromote
        />,
      ),
    );

    fireEvent.click(await screen.findByRole("button", { name: /promote draft/i }));
    expect(onPromote).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog", { name: /promote to active/i });
    expect(dialog).toHaveTextContent("draft_a");
    expect(dialog).toHaveTextContent(/becomes live/i);
    expect(dialog).toHaveTextContent(/Cancel leaves the pack in Observe/i);
    expect(screen.getByTestId("promote-pack-metrics")).toHaveTextContent(/not loaded/i);
    expect(screen.getByTestId("promote-rule-hit-rate")).toHaveTextContent(/not loaded/i);
    expect(screen.getByTestId("promote-shadow-divergence")).toHaveTextContent(/not loaded/i);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onPromote).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /promote draft/i })).toBeInTheDocument();
  });

  it("Confirm on Promote draft calls the existing promote handler", async () => {
    const onPromote = vi.fn();
    render(
      wrap(
        <ObserveEasePanel
          tenantId="demo"
          drafts={[{ name: "draft_a", file: "draft_a.json" }]}
          promoteAllowed
          blockers={[]}
          slipRules={[]}
          selectedDraft="draft_a"
          onSelectDraft={() => {}}
          onPromote={onPromote}
          canPromote
        />,
      ),
    );

    fireEvent.click(await screen.findByRole("button", { name: /promote draft/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(onPromote).toHaveBeenCalledTimes(1);
    expect(client.shadow.setPackMode).not.toHaveBeenCalled();
  });

  it("SentencePackPanel is reachable from Observe without a tribal URL", async () => {
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
    expect(await screen.findByTestId("sentence-pack-panel")).toBeInTheDocument();
    const preview = screen.getByTestId("sentence-pack-json-preview") as HTMLTextAreaElement;
    expect(preview).toBeInTheDocument();
    expect(preview.value).toContain('"mode": "shadow"');
  });

  it("three plain-English sections: Ready to Promote, Suggest Demote, Live packs", async () => {
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
    expect(await screen.findByTestId("ready-to-promote")).toHaveTextContent("draft_a");
    expect(screen.getByRole("heading", { name: "Ready to Promote" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Suggest Demote" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Live / Active packs" })).toBeInTheDocument();
    expect(screen.getByTestId("suggest-demote-empty")).toHaveTextContent(/not a red alert/i);
    expect(screen.getByTestId("suggest-demote-empty")).toHaveTextContent(/nothing auto-demotes/i);
    expect(screen.queryByText(/inbox is clear/i)).not.toBeInTheDocument();
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

  it("suggestion row shows pack id, numbers, and English reason", async () => {
    vi.mocked(client.decisions.demoteSuggestions).mockResolvedValue({
      suggestions: [
        {
          pack_id: "rot_pack",
          rule_hit_rate: 0.75,
          shadow_divergence: 0.8,
          fp_count: 1,
          reason_code: "high_shadow_divergence",
          action: "suggest_propose_demote",
        },
      ],
    });
    render(
      wrap(
        <ObserveEasePanel
          tenantId="acme"
          drafts={[]}
          promoteAllowed={false}
          blockers={[]}
          slipRules={[]}
          selectedDraft=""
          onSelectDraft={() => {}}
          onPromote={() => {}}
          canPromote={false}
        />,
      ),
    );
    const row = await screen.findByTestId("suggest-demote-rot_pack");
    expect(row).toHaveTextContent("rot_pack");
    expect(row).toHaveTextContent("75%");
    expect(row).toHaveTextContent("80%");
    expect(row).toHaveTextContent(/shadow divergence/i);
    expect(screen.queryByTestId("suggest-demote-empty")).not.toBeInTheDocument();
  });

  it("suggestion click opens Propose Demote prefilled and does not confirm", async () => {
    vi.mocked(client.decisions.demoteSuggestions).mockResolvedValue({
      suggestions: [
        {
          pack_id: "live_a",
          rule_hit_rate: 0.2,
          shadow_divergence: 0.9,
          fp_count: 0,
          reason_code: "high_shadow_divergence",
          action: "suggest_propose_demote",
        },
      ],
    });
    render(
      wrap(
        <ObserveEasePanel
          tenantId="acme"
          drafts={[]}
          promoteAllowed={false}
          blockers={[]}
          slipRules={[]}
          selectedDraft=""
          onSelectDraft={() => {}}
          onPromote={() => {}}
          canPromote={false}
        />,
      ),
    );
    const propose = await screen.findByRole("button", { name: /propose live_a/i });
    await waitFor(() => {
      expect((propose as HTMLButtonElement).disabled).toBe(false);
    });
    fireEvent.click(propose);
    await waitFor(() => {
      expect(client.rules.proposeDemote).toHaveBeenCalledWith(
        "live_a.json",
        expect.stringMatching(/high_shadow_divergence|shadow divergence/i),
        "acme",
      );
    });
    const reason = client.rules.proposeDemote.mock.calls[0][1] as string;
    expect(reason.length).toBeGreaterThanOrEqual(8);
    expect(client.rules.confirmDemote).not.toHaveBeenCalled();
    expect(client.shadow.setPackMode).not.toHaveBeenCalled();
  });
});
