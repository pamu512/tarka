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
    vi.mocked(client.decisions.byomStatus).mockResolvedValue({
      connected: false,
      backend: "",
      model: "",
    });
    vi.mocked(client.shadow.setPackMode).mockResolvedValue({
      file: "draft_a.json",
      mode: "shadow",
    });
  });

  it("human demote PUT uses shadow.setPackMode", async () => {
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

    fireEvent.click(screen.getByRole("button", { name: /human demote/i }));
    await waitFor(() => {
      expect(client.shadow.setPackMode).toHaveBeenCalledWith("draft_a.json", "shadow");
    });
  });
});
