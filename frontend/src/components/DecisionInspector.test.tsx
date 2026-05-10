import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/context/ToastContext";

import { DecisionInspector, DETERMINISTIC_AI_BYPASS_LABEL } from "./DecisionInspector";

const { getAudit } = vi.hoisted(() => ({
  getAudit: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    decisions: {
      ...actual.decisions,
      getAudit,
    },
  };
});

function renderInspector(ui: ReactElement) {
  return render(<ToastProvider>{ui}</ToastProvider>);
}

describe("DecisionInspector", () => {
  it("shows deterministic bypass label when Shadow AI trace is empty", async () => {
    getAudit.mockResolvedValue({
      trace_id: "deterministic-ai-bypass-demo",
      entity_id: "e",
      tenant_id: "demo",
      event_type: "payment",
      decision: "deny",
      score: 99,
      tags: [],
      rule_hits: ["x"],
      created_at: "2026-01-01T00:00:00Z",
      explanation_drivers: [],
      inference_context: {
        schema_version: "3",
        driver_explain: [],
        ml_top_factors: [],
        ml_summary: null,
        driver_reasons: ["rule:block"],
      },
      fallback_reason: "rules_only",
      evaluate_payload: { transaction_id: "deterministic-ai-bypass-demo", amount_cents: 100 },
    });

    renderInspector(
      <DecisionInspector
        tenantId="demo"
        traceId="deterministic-ai-bypass-demo"
        open
        onClose={() => {}}
      />,
    );

    expect(await screen.findByText(DETERMINISTIC_AI_BYPASS_LABEL)).toBeInTheDocument();
    expect(screen.getByText(/fallback_reason:/)).toBeInTheDocument();
  });

  it("Copy JSON writes combined audit payload", async () => {
    getAudit.mockResolvedValue({
      trace_id: "trace-a",
      entity_id: "e",
      tenant_id: "demo",
      event_type: "payment",
      decision: "review",
      score: 50,
      tags: [],
      rule_hits: [],
      created_at: "2026-01-01T00:00:00Z",
      explanation_drivers: [
        { reason: "r1", category: "rules", label: "L", rank: 1, source: "driver_reasons" },
      ],
      evaluate_payload: { schema_version: "1", transaction_id: "trace-a" },
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    renderInspector(
      <DecisionInspector tenantId="demo" traceId="trace-a" open onClose={() => {}} />,
    );

    await waitFor(() => expect(screen.getByRole("button", { name: "Copy JSON" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Copy JSON" }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const payload = writeText.mock.calls[0]![0] as string;
    expect(payload).toContain('"trace_id": "trace-a"');
    expect(payload).toContain('"transaction_schema"');
    expect(payload).toContain('"shadow_thought_trace"');

    vi.unstubAllGlobals();
  });
});
