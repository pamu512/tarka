import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { DegradedModeBanner } from "./DegradedModeBanner";

describe("DegradedModeBanner", () => {
  it("renders amber degraded warnings", () => {
    render(
      <DegradedModeBanner
        warnings={["Hourly trend data unavailable", "Top entities data unavailable"]}
      />,
    );
    expect(screen.getByText(/Some panels are degraded/i)).toBeInTheDocument();
    expect(screen.getByText(/Hourly trend data unavailable/)).toBeInTheDocument();
  });

  it("renders blocking error with support id hint and retry", () => {
    const onRetry = vi.fn();
    render(
      <DegradedModeBanner
        error="Case queue is temporarily unavailable while we load cases. Support ID: case-77."
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("code")).toHaveTextContent("case-77");
    screen.getByRole("button", { name: "Retry" }).click();
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
