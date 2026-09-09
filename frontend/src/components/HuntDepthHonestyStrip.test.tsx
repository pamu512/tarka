import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HuntDepthHonestyStrip } from "./HuntDepthHonestyStrip";
import { HUNT_DEPTH_CAPPED, resolveHuntDepthHonesty } from "../domain/huntDepthHonesty";

const FORBIDDEN = [
  /neo4j[- ]class/i,
  /unlimited path/i,
  /variable-length path/i,
  /identity SKU/i,
  /\b(sift|forter|riskified|feedzai|featurespace|unit21|sardine|datavisor)\b/i,
];

describe("HuntDepthHonestyStrip", () => {
  it("empty GRAPH_SERVICE_URL is plane-off English, not a spinner or fake nodes", () => {
    render(
      <HuntDepthHonestyStrip
        honesty={resolveHuntDepthHonesty({ graphServiceUrl: "", depthRequested: 2 })}
      />,
    );
    const el = screen.getByTestId("hunt-depth-honesty");
    expect(el).toHaveAttribute("role", "status");
    expect(el).toHaveTextContent(/GRAPH_SERVICE_URL is empty/i);
    expect(el).toHaveTextContent(/hops are off/i);
    expect(el.innerHTML).not.toMatch(/animate-spin/);
    expect(el.querySelectorAll("[data-graph-node]").length).toBe(0);
  });

  it("shows degrade chip when requested depth exceeds AGE-safe max", () => {
    render(
      <HuntDepthHonestyStrip
        honesty={resolveHuntDepthHonesty({
          graphServiceUrl: "http://graph-service:8001",
          depthRequested: 3,
        })}
      />,
    );
    const el = screen.getByTestId("hunt-depth-honesty");
    expect(el).toHaveTextContent(/requested 3/i);
    expect(el).toHaveTextContent(/depth not yet reported/i);
    expect(el).toHaveTextContent(/hunt:depth_capped/);
    expect(el.textContent ?? "").not.toMatch(/unlimited/i);
    for (const pat of FORBIDDEN) {
      expect(el.textContent ?? "").not.toMatch(pat);
    }
  });

  it("live API depth_applied=1 + hunt:depth_capped shows those numbers, not the stub", () => {
    render(
      <HuntDepthHonestyStrip
        honesty={resolveHuntDepthHonesty({
          graphServiceUrl: "http://graph-service:8001",
          depthRequested: 5,
          api: {
            hunt_depth_max: 1,
            depth_requested: 5,
            depth_applied: 1,
            degrade_reason: HUNT_DEPTH_CAPPED,
          },
        })}
      />,
    );
    const el = screen.getByTestId("hunt-depth-honesty");
    expect(el).toHaveTextContent(/requested 5/i);
    expect(el).toHaveTextContent(/applied 1/);
    expect(el).toHaveTextContent(/hunt:depth_capped/);
    expect(el).not.toHaveTextContent(/depth not yet reported/i);
    expect(el.textContent ?? "").not.toMatch(/unlimited/i);
    for (const pat of FORBIDDEN) {
      expect(el.textContent ?? "").not.toMatch(pat);
    }
  });
});
