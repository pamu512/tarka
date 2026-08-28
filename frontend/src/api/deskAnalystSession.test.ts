import { afterEach, describe, expect, it } from "vitest";

import {
  clearDeskAnalystApiKey,
  getDeskAnalystApiKey,
  hasDeskAnalystSession,
  setDeskAnalystApiKey,
} from "./deskAnalystSession";

describe("deskAnalystSession", () => {
  afterEach(() => {
    clearDeskAnalystApiKey();
  });

  it("starts empty (viewer)", () => {
    expect(getDeskAnalystApiKey()).toBeNull();
    expect(hasDeskAnalystSession()).toBe(false);
  });

  it("stores a pasted seed key in sessionStorage only", () => {
    setDeskAnalystApiKey("desk-analyst-local");
    expect(getDeskAnalystApiKey()).toBe("desk-analyst-local");
    expect(hasDeskAnalystSession()).toBe(true);
    expect(localStorage.getItem("tarka.desk_analyst_api_key")).toBeNull();
  });

  it("clears blank input instead of storing whitespace", () => {
    setDeskAnalystApiKey("desk-analyst-local");
    setDeskAnalystApiKey("   ");
    expect(getDeskAnalystApiKey()).toBeNull();
  });
});
