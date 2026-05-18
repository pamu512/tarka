import { describe, expect, it } from "vitest";
import { isHeroHotkeyEventIgnored } from "./heroHotkeys";

describe("isHeroHotkeyEventIgnored", () => {
  it("ignores when meta/ctrl/alt held", () => {
    expect(isHeroHotkeyEventIgnored({ defaultPrevented: false, ctrlKey: true } as KeyboardEvent)).toBe(true);
    expect(isHeroHotkeyEventIgnored({ defaultPrevented: false, metaKey: true } as KeyboardEvent)).toBe(true);
  });

  it("allows bare key on body for heroes", () => {
    expect(isHeroHotkeyEventIgnored({ defaultPrevented: false, target: document.body } as unknown as KeyboardEvent)).toBe(
      false,
    );
  });
});
