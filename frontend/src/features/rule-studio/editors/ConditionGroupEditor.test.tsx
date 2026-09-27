import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ConditionGroupEditor } from "./ConditionGroupEditor";
import { catalogToFields } from "../registry/catalogToFields";
import { fallbackAuthorCatalog } from "../../../domain/authorCatalogFallback";
import { usePackDraftStore } from "../store/packDraftStore";
import flatExt from "../fixtures/flat-when-extended-op.json";

describe("ConditionGroupEditor", () => {
  beforeEach(() => {
    usePackDraftStore.getState().reset();
    usePackDraftStore.getState().loadFromJson(flatExt);
  });

  it("updates store when op changes; starts_with uses generic JSON value input", () => {
    const fields = catalogToFields(fallbackAuthorCatalog());
    const draft = usePackDraftStore.getState().draft;
    const rule = draft.rules[0];
    const cond = rule.when[0];

    render(
      <ConditionGroupEditor
        ruleId={rule.id}
        conditions={rule.when}
        fields={fields}
        onChange={(cid, patch) => usePackDraftStore.getState().setCondition(rule.id, cid, patch)}
        onAdd={() => usePackDraftStore.getState().addCondition(rule.id)}
        onRemove={(cid) => usePackDraftStore.getState().removeCondition(rule.id, cid)}
        onMove={(cid, dir) => usePackDraftStore.getState().moveCondition(rule.id, cid, dir)}
      />,
    );

    expect(
      screen.getByLabelText(/Value for email \(JSON\)/i),
    ).toBeTruthy();

    const opSelect = screen.getByLabelText("Operator");
    fireEvent.change(opSelect, { target: { value: "contains" } });
    expect(usePackDraftStore.getState().draft.rules[0].when[0].op).toBe("contains");
    expect(usePackDraftStore.getState().dirty).toBe(true);

    // restore starts_with path for generic assertion
    usePackDraftStore.getState().setCondition(rule.id, cond.id, { op: "starts_with" });
  });
});
