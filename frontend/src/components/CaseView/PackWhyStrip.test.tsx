import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PackWhyStrip } from "./PackWhyStrip";
import { PACK_WHY_MISSING, resolvePackWhy } from "../../utils/packWhy";

describe("PackWhyStrip", () => {
  it("shows pack label and why text when pack + why are present", () => {
    render(
      <PackWhyStrip
        packId="fintech"
        packName="Fintech starter"
        behaviorTags={[]}
        why="Velocity burst on this card"
        hop={null}
        advise={null}
      />,
    );
    expect(screen.getByTestId("pack-why-strip")).toBeInTheDocument();
    expect(screen.getByTestId("pack-why-pack")).toHaveTextContent("Fintech starter (fintech)");
    expect(screen.getByTestId("pack-why-reason")).toHaveTextContent("Velocity burst on this card");
    expect(screen.getByTestId("pack-why-reason").querySelector(".italic")).toBeNull();
  });

  it("missing why shows PACK_WHY_MISSING — never invents from ML or recommended_action", () => {
    const view = resolvePackWhy({
      rule_pack_file: "fintech.json",
      evaluate_payload: {
        ml_summary: "ML risk score 71 — review recommended",
        recommended_action: "manual_review",
        reasoning: "rules=velocity_guard; fallback=rules_only",
      },
    });
    render(<PackWhyStrip {...view} />);
    const reason = screen.getByTestId("pack-why-reason");
    expect(reason).toHaveTextContent(PACK_WHY_MISSING);
    expect(reason.textContent).toContain("missing");
    expect(reason.querySelector(".italic")).not.toBeNull();
    expect(reason).not.toHaveTextContent(/ML risk score|manual_review|review recommended/i);
  });

  it("missing pack id shows PACK_WHY_MISSING on pack-why-pack", () => {
    render(
      <PackWhyStrip
        packId={PACK_WHY_MISSING}
        packName={PACK_WHY_MISSING}
        behaviorTags={[]}
        why={PACK_WHY_MISSING}
        hop={null}
        advise={null}
      />,
    );
    const pack = screen.getByTestId("pack-why-pack");
    expect(pack).toHaveTextContent(PACK_WHY_MISSING);
    expect(pack.textContent).toContain("missing");
    expect(pack.querySelector(".italic")).not.toBeNull();
  });

  it("renders pack-why-behavior only when behavior tags are present", () => {
    const { unmount } = render(
      <PackWhyStrip
        packId="device_signals"
        packName="device_signals"
        behaviorTags={["behavior:no_mouse", "behavior:superhuman_typing"]}
        why="vpn"
        hop={null}
        advise={null}
      />,
    );
    expect(screen.getByTestId("pack-why-behavior")).toHaveTextContent(
      "behavior:no_mouse · behavior:superhuman_typing",
    );
    unmount();

    render(
      <PackWhyStrip
        packId="device_signals"
        packName="device_signals"
        behaviorTags={[]}
        why="vpn"
        hop={null}
        advise={null}
      />,
    );
    expect(screen.queryByTestId("pack-why-behavior")).not.toBeInTheDocument();
  });

  it("leftover with pack id but no receipt-why mounts strip with why = missing", () => {
    // Leftover-shaped audit: pack present, no pack_reason / rule_hits / driver.
    const view = resolvePackWhy({
      pack_id: "device_signals",
      rule_pack_file: "device_signals.json",
      evaluate_payload: {
        pack_id: "device_signals",
        ml_summary: "Bot-like session — escalate",
        recommended_action: "deny",
      },
    });
    expect(view.packId).toBe("device_signals");
    expect(view.why).toBe(PACK_WHY_MISSING);

    render(<PackWhyStrip {...view} />);
    expect(screen.getByTestId("pack-why-strip")).toBeInTheDocument();
    expect(screen.getByTestId("pack-why-pack")).toHaveTextContent("device_signals");
    const reason = screen.getByTestId("pack-why-reason");
    expect(reason).toHaveTextContent(PACK_WHY_MISSING);
    expect(reason).not.toHaveTextContent(/Bot-like|escalate|deny/i);
  });
});
