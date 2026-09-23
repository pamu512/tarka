import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { EntitySetPanel } from "./EntitySetPanel";
import * as client from "@/api/client";

describe("EntitySetPanel", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("saves canvas ids as a named set (deduped, capped at 10)", () => {
    render(
      <EntitySetPanel
        tenantId="t1"
        canvasEntityIds={["a", "a", "b", ...Array.from({ length: 12 }, (_, i) => `x${i}`)]}
        onLoadSet={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByTestId("entity-set-name"), { target: { value: "ring A" } });
    fireEvent.click(screen.getByTestId("entity-set-save"));
    const stored = JSON.parse(localStorage.getItem("tarka.graph.entity_sets") || "[]");
    expect(stored).toHaveLength(1);
    expect(stored[0].name).toBe("ring A");
    expect(stored[0].entityIds).toHaveLength(10);
    expect(stored[0].entityIds[0]).toBe("a");
  });

  it("persists sets across mounts and removes them", () => {
    localStorage.setItem(
      "tarka.graph.entity_sets",
      JSON.stringify([{ name: "s1", entityIds: ["a"], createdAt: "2026-01-01T00:00:00Z" }]),
    );
    render(<EntitySetPanel tenantId="t1" canvasEntityIds={[]} onLoadSet={vi.fn()} />);
    expect(screen.getByText("s1")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Remove set s1"));
    expect(screen.queryByText("s1")).toBeNull();
    expect(JSON.parse(localStorage.getItem("tarka.graph.entity_sets") || "[]")).toHaveLength(0);
  });

  it("loads a set onto the canvas filter via onLoadSet", () => {
    localStorage.setItem(
      "tarka.graph.entity_sets",
      JSON.stringify([{ name: "s1", entityIds: ["a", "b"], createdAt: "2026-01-01T00:00:00Z" }]),
    );
    const onLoad = vi.fn();
    render(<EntitySetPanel tenantId="t1" canvasEntityIds={[]} onLoadSet={onLoad} />);
    fireEvent.click(screen.getByText("s1"));
    expect(onLoad).toHaveBeenCalledWith(["a", "b"]);
  });

  it("renders the trace-cited timeline and links each row", async () => {
    localStorage.setItem(
      "tarka.graph.entity_sets",
      JSON.stringify([{ name: "s1", entityIds: ["a", "b"], createdAt: "2026-01-01T00:00:00Z" }]),
    );
    const spy = vi.spyOn(client.decisions, "entityTimeline").mockResolvedValue({
      schema_id: "tarka.entity_timeline/v1",
      entities: [
        { entity_id: "a", count: 1 },
        { entity_id: "b", count: 1 },
      ],
      timeline: [
        {
          entity_id: "a",
          trace_id: "11111111-1111-1111-1111-111111111111",
          short_id: "1111",
          event_type: "evaluate",
          decision: "DENY",
          amount: null,
          currency: null,
          rule_result: "DENY",
          tags: [],
          ai_confidence: null,
          created_at: "2026-09-01T00:00:00Z",
        },
        {
          entity_id: "b",
          trace_id: "22222222-2222-2222-2222-222222222222",
          short_id: "2222",
          event_type: "evaluate",
          decision: "ALLOW",
          amount: null,
          currency: null,
          rule_result: "ALLOW",
          tags: [],
          ai_confidence: null,
          created_at: "2026-09-01T01:00:00Z",
        },
      ],
      total: 2,
    } as unknown as client.EntityTimelineResponse);
    render(<EntitySetPanel tenantId="t1" canvasEntityIds={[]} onLoadSet={vi.fn()} />);
    fireEvent.click(screen.getByTestId("entity-set-timeline-s1"));
    await waitFor(() => expect(screen.getByTestId("entity-timeline-count").textContent).toBe("2 rows"));
    const links = screen.getAllByText("trace");
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute("href")).toContain("trace_id=11111111-1111-1111-1111-111111111111");
    expect(screen.getByText("DENY")).toBeTruthy();
  });

  it("shows an error string (not a toast) when the decision plane is down", async () => {
    localStorage.setItem(
      "tarka.graph.entity_sets",
      JSON.stringify([{ name: "s1", entityIds: ["a"], createdAt: "2026-01-01T00:00:00Z" }]),
    );
    vi.spyOn(client.decisions, "entityTimeline").mockRejectedValue(new Error("down"));
    render(<EntitySetPanel tenantId="t1" canvasEntityIds={[]} onLoadSet={vi.fn()} />);
    fireEvent.click(screen.getByTestId("entity-set-timeline-s1"));
    await waitFor(() => expect(screen.getByTestId("entity-timeline-error")).toBeTruthy());
  });
});

describe("EntitySetPanel polish", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("color-codes timeline rows per entity (stable assignment)", async () => {
    localStorage.setItem(
      "tarka.graph.entity_sets",
      JSON.stringify([{ name: "s1", entityIds: ["alpha", "beta"], createdAt: "2026-01-01T00:00:00Z" }]),
    );
    vi.spyOn(client.decisions, "entityTimeline").mockResolvedValue({
      schema_id: "tarka.entity_timeline/v1",
      entities: [
        { entity_id: "alpha", count: 1 },
        { entity_id: "beta", count: 1 },
      ],
      timeline: [
        mk("alpha", "11111111-1111-1111-1111-111111111111", "DENY", "2026-09-01T00:00:00Z"),
        mk("beta", "22222222-2222-2222-2222-222222222222", "ALLOW", "2026-09-01T01:00:00Z"),
      ],
      total: 2,
    } as unknown as client.EntityTimelineResponse);
    render(<EntitySetPanel tenantId="t1" canvasEntityIds={[]} onLoadSet={vi.fn()} />);
    fireEvent.click(screen.getByTestId("entity-set-timeline-s1"));
    await waitFor(() => screen.getByTestId("entity-timeline-count"));
    const chips = screen.getAllByTestId("timeline-entity-chip");
    expect(chips).toHaveLength(2);
    expect(chips[0].className).not.toBe(chips[1].className);
  });

  it("shows relative timestamps on timeline rows", async () => {
    localStorage.setItem(
      "tarka.graph.entity_sets",
      JSON.stringify([{ name: "s1", entityIds: ["alpha"], createdAt: "2026-01-01T00:00:00Z" }]),
    );
    vi.spyOn(client.decisions, "entityTimeline").mockResolvedValue({
      schema_id: "tarka.entity_timeline/v1",
      entities: [{ entity_id: "alpha", count: 1 }],
      timeline: [mk("alpha", "33333333-3333-3333-3333-333333333333", "REVIEW", new Date().toISOString())],
      total: 1,
    } as unknown as client.EntityTimelineResponse);
    render(<EntitySetPanel tenantId="t1" canvasEntityIds={[]} onLoadSet={vi.fn()} />);
    fireEvent.click(screen.getByTestId("entity-set-timeline-s1"));
    await waitFor(() => screen.getByTestId("entity-timeline-count"));
    expect(screen.getByTestId("timeline-row-time").textContent).toMatch(/now|s ago|m ago|h ago/);
  });

  it("shows per-entity decision counts in the timeline header", async () => {
    localStorage.setItem(
      "tarka.graph.entity_sets",
      JSON.stringify([{ name: "s1", entityIds: ["alpha", "beta"], createdAt: "2026-01-01T00:00:00Z" }]),
    );
    vi.spyOn(client.decisions, "entityTimeline").mockResolvedValue({
      schema_id: "tarka.entity_timeline/v1",
      entities: [
        { entity_id: "alpha", count: 2 },
        { entity_id: "beta", count: 0 },
      ],
      timeline: [mk("alpha", "44444444-4444-4444-4444-444444444444", "DENY", "2026-09-01T00:00:00Z")],
      total: 1,
    } as unknown as client.EntityTimelineResponse);
    render(<EntitySetPanel tenantId="t1" canvasEntityIds={[]} onLoadSet={vi.fn()} />);
    fireEvent.click(screen.getByTestId("entity-set-timeline-s1"));
    await waitFor(() => screen.getByTestId("entity-timeline-count"));
    expect(screen.getByTestId("timeline-entity-counts").textContent).toContain("alpha");
    expect(screen.getByTestId("timeline-entity-counts").textContent).toContain("beta");
    expect(screen.getByTestId("timeline-entity-counts").textContent).toContain("2");
    expect(screen.getByTestId("timeline-entity-counts").textContent).toContain("0");
  });
});

function mk(entityId: string, traceId: string, decision: string, createdAt: string) {
  return {
    entity_id: entityId,
    trace_id: traceId,
    short_id: traceId.slice(0, 4),
    event_type: "evaluate",
    decision,
    amount: null,
    currency: null,
    rule_result: decision,
    tags: [],
    ai_confidence: null,
    created_at: createdAt,
  };
}
