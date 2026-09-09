import type { ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { graph } from "@/api/client";
import { TenantEnvironmentProvider } from "@/context/TenantEnvironmentContext";
import { ToastProvider } from "@/context/ToastContext";
import GraphInvestigationPage from "@/pages/GraphInvestigationPage";

vi.mock("@/context/FailoverPlaneContext", () => ({
  useFailoverPlanes: () => ({
    loading: false,
    error: null,
    graphPlaneDisabled: false,
    aiPlaneDisabled: false,
    graphLatencyMsP95: null,
    aiLatencyMsP95: null,
    updatedAt: null,
    refresh: async () => {},
    setPlanes: async () => {},
  }),
}));

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  const emptySub = { nodes: [], edges: [] };
  return {
    ...actual,
    graph: {
      ...actual.graph,
      subgraph: vi.fn().mockResolvedValue(emptySub),
      entityLinks: vi.fn().mockResolvedValue({ edges: [], attention: [] }),
      schema: vi.fn().mockResolvedValue({ entity_types: [] }),
      searchEntities: vi.fn().mockResolvedValue({ entities: [] }),
      entityRiskTop: vi.fn().mockResolvedValue({ entities: [] }),
      growthPolicy: vi.fn().mockResolvedValue({ windows: [] }),
      communities: vi.fn().mockResolvedValue({ communities: [] }),
      fraudRings: vi.fn().mockResolvedValue({ rings: [] }),
    },
  };
});

function wrap(ui: ReactElement, path: string) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider>
        <TenantEnvironmentProvider>
          <Routes>
            <Route path="/graph" element={ui} />
          </Routes>
        </TenantEnvironmentProvider>
      </ToastProvider>
    </MemoryRouter>
  );
}

describe("GraphInvestigationPage Hunt honesty", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.mocked(graph.subgraph).mockResolvedValue({ nodes: [], edges: [] });
  });

  it("empty GRAPH_SERVICE_URL shows plane-off English, not a spinner or fake nodes", () => {
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "");
    render(wrap(<GraphInvestigationPage />, "/graph?entity_id=buyer-1&depth=3"));
    expect(screen.getByRole("status")).toHaveTextContent(/GRAPH_SERVICE_URL is empty/i);
    expect(screen.getByRole("status")).toHaveTextContent(/hops are off/i);
    expect(document.querySelector(".animate-spin")).toBeNull();
    expect(screen.queryByText(/Top scored entities/i)).toBeNull();
    expect(screen.queryByText(/Subgraph returned no nodes/i)).toBeNull();
  });

  it("depth_requested above AGE-safe max shows degrade with applied + reason", () => {
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "http://graph-service:8001");
    render(wrap(<GraphInvestigationPage />, "/graph?entity_id=buyer-1&depth=3"));
    const el = screen.getByTestId("hunt-depth-honesty");
    expect(el).toHaveTextContent(/requested 3/i);
    expect(el).toHaveTextContent(/depth not yet reported/i);
    expect(el).toHaveTextContent(/hunt:depth_capped/);
  });

  it("live subgraph payload depth_applied=1 + hunt:depth_capped shows those numbers, not the stub", async () => {
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "http://graph-service:8001");
    vi.mocked(graph.subgraph).mockResolvedValue({
      nodes: [],
      edges: [],
      schema_id: "tarka.hunt_depth/v1",
      hunt_depth_max: 1,
      depth_requested: 5,
      depth_applied: 1,
      degrade_reason: "hunt:depth_capped",
    });
    render(wrap(<GraphInvestigationPage />, "/graph?entity_id=buyer-1&depth=5"));
    await waitFor(() => {
      const el = screen.getByTestId("hunt-depth-honesty");
      expect(el).toHaveTextContent(/applied 1/);
      expect(el).toHaveTextContent(/hunt:depth_capped/);
      expect(el).not.toHaveTextContent(/depth not yet reported/i);
    });
  });
});
