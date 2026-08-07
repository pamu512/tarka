import { describe, expect, it } from "vitest";
import {
  auditCapability,
  calibrationCapability,
  calibrationPostureWarnings,
  capabilityDownWarnings,
  graphCapability,
} from "./capabilityStatus";

describe("capabilityStatus", () => {
  it("marks audit missing without trace", () => {
    expect(auditCapability(false, true)).toBe("missing");
    expect(auditCapability(true, true)).toBe("ok");
    expect(auditCapability(true, false)).toBe("down");
  });

  it("maps graph fetch outcomes", () => {
    expect(graphCapability(null)).toBe("missing");
    expect(graphCapability(true)).toBe("ok");
    expect(graphCapability(false)).toBe("down");
  });

  it("marks calibration down only on fetch failure", () => {
    expect(calibrationCapability(null, null)).toBe("missing");
    expect(calibrationCapability(false, null)).toBe("down");
    expect(calibrationCapability(true, false)).toBe("ok");
    expect(calibrationCapability(true, true)).toBe("ok");
  });

  it("lists warnings only for down capabilities", () => {
    expect(
      capabilityDownWarnings({ audit: "ok", graph: "down", calibration: "missing" }),
    ).toEqual(["Graph risk unavailable — topology signals cannot be trusted this session"]);
  });

  it("warns when calibration reachable but posture unhealthy", () => {
    expect(calibrationPostureWarnings("ok", "insufficient labels")).toEqual([
      "Calibration posture not healthy — insufficient labels",
    ]);
    expect(calibrationPostureWarnings("ok", "healthy")).toEqual([]);
    expect(calibrationPostureWarnings("down", "insufficient labels")).toEqual([]);
  });
});
