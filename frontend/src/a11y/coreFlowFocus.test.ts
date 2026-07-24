import { describe, expect, it } from "vitest";
import { assertLandmarkContract, CORE_FLOW_LANDMARKS } from "./coreFlowFocus";

describe("core flow a11y landmarks", () => {
  it("defines cases/rules/investigation routes", () => {
    expect(CORE_FLOW_LANDMARKS.map((x) => x.route)).toEqual([
      "/cases",
      "/rules",
      "/investigation",
    ]);
  });

  it("flags missing main/heading", () => {
    const missing = assertLandmarkContract({
      querySelector: () => null,
    });
    expect(missing).toContain("main");
    expect(missing).toContain("heading");
  });
});
