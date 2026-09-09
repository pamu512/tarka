import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { TuneRuleModal } from "./TuneRuleModal";

vi.mock("../../api/client", () => ({
  rules: { list: vi.fn() },
  shadow: {},
}));

describe("TuneRuleModal", () => {
  it("does not market the legacy canvas as a full-page builder SKU", () => {
    render(
      <MemoryRouter>
        <TuneRuleModal open onClose={() => undefined} ruleHits={["probe_1"]} />
      </MemoryRouter>,
    );
    const body = document.body.textContent ?? "";
    expect(body).toMatch(/not a product SKU/i);
    expect(body).not.toMatch(/full-page builder/i);
    expect(body).not.toMatch(/Visual Rule Builder/i);
  });
});
