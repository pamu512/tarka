import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { MultiPartyLinksResponse } from "../../api/client";
import {
  MultiPartyLinksDesktopRail,
  type MultiPartyLinksRailState,
} from "./MultiPartyLinksRail";

const fixture: MultiPartyLinksResponse = {
  case_id: "case-anchor",
  entity_id: "anchor-ent",
  tenant_id: "t-collusion",
  links: [
    {
      entity_id: "neighbor-1",
      roles: ["courier"],
      distance: 1,
      propagated_risk_score: 0.42,
      path_description: "(anchor)-[SHARED_DEVICE]->(neighbor-1)",
      shared_signals: ["shared_device"],
      cases: [
        {
          case_id: "case-neighbor",
          status: "resolved_fraud",
          disposition_reason: "collusion",
        },
      ],
    },
  ],
};

function readyState(data: MultiPartyLinksResponse): MultiPartyLinksRailState {
  return { data, loading: false, error: null, reload: vi.fn() };
}

describe("MultiPartyLinksRail", () => {
  it("renders courier role chip and linked case href from fixture", () => {
    render(
      <MemoryRouter>
        <MultiPartyLinksDesktopRail
          caseId="case-anchor"
          tenantId="t-collusion"
          state={readyState(fixture)}
        />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("multi-party-links-rail")).toBeInTheDocument();
    expect(screen.getByText("courier")).toBeInTheDocument();
    expect(screen.getByText("neighbor-1")).toBeInTheDocument();
    const caseLink = screen.getByRole("link", { name: /case-neighbor/i });
    expect(caseLink).toHaveAttribute("href", "/cases/case-neighbor?tenant_id=t-collusion");
  });

  it("shows degraded banner when graph is unavailable", () => {
    render(
      <MemoryRouter>
        <MultiPartyLinksDesktopRail
          caseId="case-anchor"
          tenantId="t-collusion"
          state={readyState({
            ...fixture,
            links: [],
            degraded: true,
            degraded_reason: "graph_unavailable",
          })}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(/graph unavailable/i)).toBeInTheDocument();
  });
});
