import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/config/leanNav", () => ({ DESK_PROFILE: "demo" }));

import { FieldMapPanel } from "./FieldMapPanel";

describe("FieldMapPanel (demo)", () => {
  it("renders nothing on demo", () => {
    const { container } = render(<FieldMapPanel tenantId="t1" />);
    expect(container.querySelector("[data-testid=field-map-panel]")).toBeNull();
  });
});
