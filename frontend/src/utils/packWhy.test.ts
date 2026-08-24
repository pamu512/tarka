import { describe, expect, it } from "vitest";

import {
  ADVISE_TIMEOUT_COPY,
  PACK_WHY_MISSING,
  packIdFromRulePackFile,
  resolvePackWhy,
} from "./packWhy";

describe("packIdFromRulePackFile", () => {
  it("uses the file stem as pack id", () => {
    expect(packIdFromRulePackFile("fintech.json")).toBe("fintech");
  });

  it("joins contributing packs from the evaluate snapshot", () => {
    expect(packIdFromRulePackFile("rules/fintech.json,payments.json")).toBe("fintech, payments");
  });

  it("returns null when the snapshot field is empty", () => {
    expect(packIdFromRulePackFile("")).toBeNull();
    expect(packIdFromRulePackFile(null)).toBeNull();
  });
});

describe("resolvePackWhy", () => {
  it("shows pack id/name and one plain-language why from existing fields", () => {
    const view = resolvePackWhy({
      rule_pack_file: "fintech.json",
      pack_name: "Fintech starter",
      driver_explain: [{ reason: "rule:velocity_guard", label: "Velocity burst on this card" }],
    });
    expect(view.packId).toBe("fintech");
    expect(view.packName).toBe("Fintech starter");
    expect(view.why).toBe("Velocity burst on this card");
    expect(view.advise).toBeNull();
  });

  it("says missing when pack reason is absent — does not invent from ML or recommended action", () => {
    const view = resolvePackWhy({
      rule_pack_file: "fintech.json",
      evaluate_payload: {
        ml_summary: "ML risk score 71 — review recommended",
        recommended_action: "manual_review",
        reasoning: "rules=velocity_guard; fallback=rules_only",
      },
    });
    expect(view.packId).toBe("fintech");
    expect(view.why).toBe(PACK_WHY_MISSING);
    expect(view.advise).toBeNull();
  });

  it("still returns a strip model when pack id is also absent", () => {
    const view = resolvePackWhy({});
    expect(view.packId).toBe(PACK_WHY_MISSING);
    expect(view.packName).toBe(PACK_WHY_MISSING);
    expect(view.why).toBe(PACK_WHY_MISSING);
    expect(view.advise).toBeNull();
  });

  it("does not render an advise slot when no advise row is on the case", () => {
    const view = resolvePackWhy({
      rule_pack_file: "fintech.json",
      pack_reason: "Card velocity exceeded the pack threshold.",
    });
    expect(view.why).toBe("Card velocity exceeded the pack threshold.");
    expect(view.advise).toBeNull();
  });

  it("surfaces an existing advise line under pack why", () => {
    const view = resolvePackWhy({
      rule_pack_file: "fintech.json",
      pack_reason: "Card velocity exceeded the pack threshold.",
      evaluate_payload: { advise: "Ask the cardholder to confirm the last three charges." },
    });
    expect(view.advise).toBe("Ask the cardholder to confirm the last three charges.");
  });

  it("uses rule_hits as the why when no pack_reason is on the evaluate snapshot", () => {
    const view = resolvePackWhy({
      rule_pack_file: "device_signals.json",
      rule_hits: ["sdk_rooted", "sdk_emulator"],
    });
    expect(view.packId).toBe("device_signals");
    expect(view.why).toBe("sdk_rooted, sdk_emulator");
    expect(view.advise).toBeNull();
  });

  it("uses the timeout copy only when advise already timed out on the case", () => {
    const view = resolvePackWhy({
      rule_pack_file: "fintech.json",
      pack_reason: "Card velocity exceeded the pack threshold.",
      evaluate_payload: { advise_status: "timed_out" },
    });
    expect(view.advise).toBe(ADVISE_TIMEOUT_COPY);
  });
});
