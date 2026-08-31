import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { cases, decisions, graph } from "@/api/client";
import { GraphContextPanel } from "@/components/GraphContextPanel";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    graph: {
      ...actual.graph,
      getEntity: vi.fn(),
      entityLinks: vi.fn(),
      entityHistory: vi.fn(),
      entityDeepContext: vi.fn(),
      latestEvaluate: vi.fn(),
      latestDisposition: vi.fn(),
    },
    decisions: {
      ...actual.decisions,
      getAudit: vi.fn(),
    },
    cases: {
      ...actual.cases,
      actOnEntity: vi.fn(),
    },
  };
});

describe("GraphContextPanel object dossier", () => {
  beforeEach(() => {
    vi.mocked(graph.getEntity).mockReset();
    vi.mocked(graph.entityLinks).mockReset();
    vi.mocked(graph.entityHistory).mockReset();
    vi.mocked(graph.entityDeepContext).mockReset();
    vi.mocked(graph.latestEvaluate).mockReset();
    vi.mocked(graph.latestEvaluate).mockResolvedValue(null);
    vi.mocked(graph.latestDisposition).mockReset();
    vi.mocked(graph.latestDisposition).mockResolvedValue(null);
    vi.mocked(decisions.getAudit).mockReset();
    vi.mocked(decisions.getAudit).mockRejectedValue(new Error("no audit"));
    vi.mocked(cases.actOnEntity).mockReset();
  });

  it("shows type, links, and last trace from the object APIs", async () => {
    vi.mocked(graph.getEntity).mockResolvedValue({
      id: "buyer-demo",
      labels: ["Person"],
      properties: {},
    });
    vi.mocked(graph.entityLinks).mockResolvedValue({
      entity_id: "buyer-demo",
      nodes: [],
      edges: [
        {
          from_id: "buyer-demo",
          to_id: "login:tr-1",
          type: "PERFORMED_LOGIN",
          properties: {},
        },
      ],
    });
    vi.mocked(graph.entityHistory).mockResolvedValue({
      entity_id: "buyer-demo",
      last_trace_id: "tr-1",
      trace_ids: ["tr-1"],
      properties: {},
    });
    vi.mocked(graph.entityDeepContext).mockResolvedValue(null);

    render(
      <GraphContextPanel
        open
        onClose={() => undefined}
        tenantId="demo"
        entityId="buyer-demo"
        embedded
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Person" })).toBeInTheDocument();
    });
    expect(screen.getByTestId("object-links")).toHaveTextContent("PERFORMED_LOGIN");
    expect(screen.getByTestId("object-links")).toHaveTextContent("login:tr-1");
    expect(screen.getByTestId("object-history")).toHaveTextContent("tr-1");
  });

  it("shows pack-why, hold state, and evaluate receipt on the link", async () => {
    vi.mocked(graph.getEntity).mockResolvedValue({
      id: "buyer-demo",
      labels: ["Person"],
      properties: { last_act: "held" },
    });
    vi.mocked(graph.entityLinks).mockResolvedValue({
      entity_id: "buyer-demo",
      nodes: [],
      edges: [
        {
          from_id: "buyer-demo",
          to_id: "dev-same",
          type: "USED_DEVICE",
          properties: { trace_id: "tr-eval-9" },
        },
      ],
    });
    vi.mocked(graph.entityHistory).mockResolvedValue({
      entity_id: "buyer-demo",
      last_trace_id: "tr-eval-9",
      trace_ids: ["tr-flag", "tr-eval-9"],
      properties: { last_act: "held" },
    });
    vi.mocked(graph.entityDeepContext).mockResolvedValue(null);
    vi.mocked(graph.latestDisposition).mockResolvedValue({
      outcome: "held",
      created_at: "2026-08-24T08:30:00Z",
      case_id: "c0-hold",
    });
    vi.mocked(decisions.getAudit).mockImplementation(async (traceId: string) => {
      if (traceId === "tr-flag") {
        return {
          trace_id: "tr-flag",
          entity_id: "buyer-demo",
          tenant_id: "demo",
          event_type: "login",
          decision: "review",
          score: 62,
          tags: ["sdk:rooted"],
          rule_hits: ["sdk_rooted"],
          rule_pack_file: "device_signals.json",
          integrity: {
            is_rooted: "true",
            is_jailbroken: "missing",
            has_biometrics: "missing",
          },
          created_at: "2026-08-24T08:00:00Z",
        };
      }
      return {
        trace_id: "tr-eval-9",
        entity_id: "buyer-demo",
        tenant_id: "demo",
        event_type: "payment",
        decision: "allow",
        score: 4,
        tags: [],
        rule_hits: [],
        created_at: "2026-08-24T09:00:00Z",
      };
    });

    render(
      <GraphContextPanel
        open
        onClose={() => undefined}
        tenantId="demo"
        entityId="buyer-demo"
        embedded
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("pack-why-strip")).toBeInTheDocument();
    });
    expect(screen.getByTestId("pack-why-pack")).toHaveTextContent("device_signals");
    expect(screen.getByTestId("pack-why-reason")).toHaveTextContent("sdk_rooted");
    expect(screen.queryByTestId("pack-why-advise")).not.toBeInTheDocument();
    expect(screen.getByTestId("device-integrity-rooted")).toHaveTextContent("true");
    expect(screen.getByTestId("device-integrity-jailbroken")).toHaveTextContent("missing");
    expect(screen.getByTestId("device-integrity-biometrics")).toHaveTextContent("missing");
    expect(screen.queryByText(/fallback=/)).not.toBeInTheDocument();
    const story = screen.getByTestId("object-story").textContent || "";
    expect(story.indexOf("allow")).toBeGreaterThan(-1);
    expect(story.indexOf("held")).toBeGreaterThan(-1);
    expect(story.indexOf("review")).toBeGreaterThan(-1);
    expect(story.indexOf("allow")).toBeLessThan(story.indexOf("held"));
    expect(story.indexOf("held")).toBeLessThan(story.indexOf("review"));
    expect(screen.getByTestId("object-evaluate")).toHaveTextContent("review");
    expect(screen.getByTestId("object-story")).toHaveTextContent("62");
    expect(screen.getByTestId("object-hold")).toHaveTextContent("held");
    expect(screen.getByTestId("object-links")).toHaveTextContent("tr-eval-9");
    expect(decisions.getAudit).toHaveBeenCalledWith("tr-flag", "demo", { detail_level: "minimal" });
    expect(decisions.getAudit).toHaveBeenCalledWith("tr-eval-9", "demo", { detail_level: "minimal" });
    expect(graph.latestDisposition).toHaveBeenCalledWith("buyer-demo", "demo");
  });

  it("re-seeds Hunt when a linked object is clicked", async () => {
    const onSelectEntity = vi.fn();
    vi.mocked(graph.getEntity).mockResolvedValue({
      id: "guest-aaa",
      labels: ["Person"],
      properties: {},
    });
    vi.mocked(graph.entityLinks).mockResolvedValue({
      entity_id: "guest-aaa",
      nodes: [],
      edges: [
        {
          from_id: "guest-aaa",
          to_id: "dev-same",
          type: "USED_DEVICE",
          properties: {},
        },
      ],
    });
    vi.mocked(graph.entityHistory).mockResolvedValue({
      entity_id: "guest-aaa",
      last_trace_id: "tr-a",
      trace_ids: ["tr-a"],
      properties: {},
    });
    vi.mocked(graph.entityDeepContext).mockResolvedValue(null);

    render(
      <GraphContextPanel
        open
        onClose={() => undefined}
        tenantId="demo"
        entityId="guest-aaa"
        embedded
        onSelectEntity={onSelectEntity}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "dev-same" })).toBeInTheDocument();
    });
    screen.getByRole("button", { name: "dev-same" }).click();
    expect(onSelectEntity).toHaveBeenCalledWith("dev-same");
  });

  it("holds the Person without rewriting the id", async () => {
    vi.mocked(graph.getEntity).mockResolvedValue({
      id: "buyer-demo",
      labels: ["Person"],
      properties: {},
    });
    vi.mocked(graph.entityLinks).mockResolvedValue({
      entity_id: "buyer-demo",
      nodes: [],
      edges: [],
    });
    vi.mocked(graph.entityHistory).mockResolvedValue({
      entity_id: "buyer-demo",
      last_trace_id: null,
      trace_ids: [],
      properties: {},
    });
    vi.mocked(graph.entityDeepContext).mockResolvedValue(null);
    vi.mocked(cases.actOnEntity).mockResolvedValue({
      entity_id: "buyer-demo",
      action: "hold",
      outcome: "held",
      case_id: "11111111-2222-3333-4444-555555555555",
      created_leftover: true,
      trace_id: "act:1",
    });

    render(
      <GraphContextPanel
        open
        onClose={() => undefined}
        tenantId="demo"
        entityId="buyer-demo"
        embedded
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Hold this person" })).toBeInTheDocument();
    });
    screen.getByRole("button", { name: "Hold this person" }).click();
    await waitFor(() => {
      expect(cases.actOnEntity).toHaveBeenCalledWith({
        tenant_id: "demo",
        entity_id: "buyer-demo",
        action: "hold",
      });
    });
    expect(await screen.findByText("Held.")).toBeInTheDocument();
    expect(screen.queryByText(/Leftover/)).not.toBeInTheDocument();
    expect(screen.queryByText(/11111111/)).not.toBeInTheDocument();
  });
});
