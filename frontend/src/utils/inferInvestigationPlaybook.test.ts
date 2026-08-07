import { describe, expect, it } from "vitest";
import {
  MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK,
  inferInvestigationPlaybookId,
} from "./inferInvestigationPlaybook";

describe("inferInvestigationPlaybookId", () => {
  it("returns marketplace COD playbook for payout-hold + courier tags", () => {
    expect(
      inferInvestigationPlaybookId(["action:payout_hold", "risk:courier_spoof"]),
    ).toBe(MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK);
  });

  it("matches vendor:incognia* and offline_payment vertical", () => {
    expect(inferInvestigationPlaybookId(["vendor:incognia_location"])).toBe(
      MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK,
    );
    expect(inferInvestigationPlaybookId(["vertical:offline_payment"])).toBe(
      MARKETPLACE_COD_COURIER_HOLD_PLAYBOOK,
    );
  });

  it("returns null for unrelated or empty tags", () => {
    expect(inferInvestigationPlaybookId(["risk:ato", "vertical:payments"])).toBeNull();
    expect(inferInvestigationPlaybookId([])).toBeNull();
    expect(inferInvestigationPlaybookId(null)).toBeNull();
  });
});
