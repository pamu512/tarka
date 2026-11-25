import { describe, it, expect, beforeEach } from "vitest";
import flat from "../fixtures/flat-when.json";
import { usePackDraftStore } from "./packDraftStore";

describe("packDraftStore", () => {
  beforeEach(() => {
    usePackDraftStore.getState().reset();
  });

  it("load → dirty false → edit → dirty true → compile → hydrate clears dirty", () => {
    const store = usePackDraftStore.getState();
    store.loadFromJson(flat);
    expect(usePackDraftStore.getState().dirty).toBe(false);

    const rule = usePackDraftStore.getState().draft.rules[0];
    const cond = rule.when[0];
    store.setCondition(rule.id, cond.id, { value: 99 });
    expect(usePackDraftStore.getState().dirty).toBe(true);

    const compiled = store.compileForSave() as {
      rules: Array<{ id: string; when: Array<{ value: unknown }> }>;
    };
    expect(compiled.rules[0].when[0].value).toBe(99);

    const serverPack = {
      ...flat,
      rules: [
        {
          ...flat.rules[0],
          id: "server_injected_id",
          when: [{ field: "event_count_1h", op: "gte", value: 99 }],
        },
        flat.rules[1],
      ],
    };
    store.hydrateFromServerPack(serverPack);
    const after = usePackDraftStore.getState();
    expect(after.dirty).toBe(false);
    expect(after.draft.rules[0].id).toBe("server_injected_id");
  });
});
