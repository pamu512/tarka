import { describe, expect, it } from "vitest";

import {
  DEVICE_INTEGRITY_MISSING,
  resolveDeviceIntegrity,
  resolveIntegrityPresence,
} from "./deviceIntegrity";

describe("resolveDeviceIntegrity", () => {
  it("says missing for every field when nothing is on the case", () => {
    const view = resolveDeviceIntegrity({});
    expect(view.rooted).toBe(DEVICE_INTEGRITY_MISSING);
    expect(view.jailbroken).toBe(DEVICE_INTEGRITY_MISSING);
    expect(view.biometrics).toBe(DEVICE_INTEGRITY_MISSING);
  });

  it("uses booleans on device_context.signals including false", () => {
    const view = resolveDeviceIntegrity({
      device_context: {
        platform: "android",
        signals: { is_rooted: true, is_jailbroken: false, has_biometrics: false },
      },
    });
    expect(view.rooted).toBe("yes");
    expect(view.jailbroken).toBe("no");
    expect(view.biometrics).toBe("no");
  });

  it("reads device_context from evaluate_payload", () => {
    const view = resolveDeviceIntegrity({
      evaluate_payload: {
        device_context: { platform: "ios", signals: { is_jailbroken: true, has_biometrics: true } },
      },
    });
    expect(view.rooted).toBe(DEVICE_INTEGRITY_MISSING);
    expect(view.jailbroken).toBe("yes");
    expect(view.biometrics).toBe("yes");
  });

  it("treats sdk:rooted / sdk:jailbroken / sdk:biometrics tags as yes when the boolean is absent", () => {
    const view = resolveDeviceIntegrity({
      tags: ["sdk:rooted", "sdk:vpn"],
      top_signals: ["sdk:jailbroken"],
    });
    expect(view.rooted).toBe("yes");
    expect(view.jailbroken).toBe("yes");
    expect(view.biometrics).toBe(DEVICE_INTEGRITY_MISSING);
  });

  it("does not invent false from always-false client fields such as is_spoofed_location", () => {
    const view = resolveDeviceIntegrity({
      device_context: {
        signals: { is_spoofed_location: false, is_bot: false },
      },
      tags: ["sdk:spoofed_location"],
    });
    expect(view.rooted).toBe(DEVICE_INTEGRITY_MISSING);
    expect(view.jailbroken).toBe(DEVICE_INTEGRITY_MISSING);
    expect(view.biometrics).toBe(DEVICE_INTEGRITY_MISSING);
  });

  it("prefers a stored boolean over a tag when both exist", () => {
    const view = resolveDeviceIntegrity({
      tags: ["sdk:rooted"],
      device_context: { signals: { is_rooted: false } },
    });
    expect(view.rooted).toBe("no");
  });
});

describe("resolveIntegrityPresence", () => {
  it("uses evaluate audit integrity map when present", () => {
    const view = resolveIntegrityPresence({
      integrity: {
        is_rooted: "true",
        is_jailbroken: "present",
        has_biometrics: "missing",
      },
    });
    expect(view.rooted).toBe("true");
    expect(view.jailbroken).toBe("present");
    expect(view.biometrics).toBe("missing");
  });

  it("derives present|missing|true and never invents false for omitted fields", () => {
    const omitted = resolveIntegrityPresence({
      device_context: { signals: { is_emulator: false } },
    });
    expect(omitted.rooted).toBe("missing");
    expect(omitted.jailbroken).toBe("missing");
    expect(omitted.biometrics).toBe("missing");

    const explicitFalse = resolveIntegrityPresence({
      device_context: { signals: { is_rooted: false } },
    });
    expect(explicitFalse.rooted).toBe("present");

    const rooted = resolveIntegrityPresence({
      device_context: { signals: { is_rooted: true } },
    });
    expect(rooted.rooted).toBe("true");
  });
});
