import { describe, it, expect } from "vitest";
import { indicativeEval } from "./indicativeEval";

describe("indicativeEval", () => {
  it("hits eq + gte conditions and sums score", () => {
    const pack = {
      version: 1,
      name: "t",
      rules: [
        {
          id: "eq_currency",
          when: [{ field: "currency", op: "eq", value: "USD" }],
          tags: [],
          score_delta: 5,
          description: "",
        },
        {
          id: "gte_amount",
          when: [{ field: "amount", op: "gte", value: 100 }],
          tags: [],
          score_delta: 10,
          description: "",
        },
      ],
    };
    const r = indicativeEval(pack, { currency: "USD", amount: 150 });
    expect(r.hits).toEqual(["eq_currency", "gte_amount"]);
    expect(r.score).toBe(15);
  });

  it("misses when eq fails", () => {
    const pack = {
      version: 1,
      name: "t",
      rules: [
        {
          id: "eq_currency",
          when: [{ field: "currency", op: "eq", value: "USD" }],
          tags: [],
          score_delta: 5,
          description: "",
        },
      ],
    };
    expect(indicativeEval(pack, { currency: "EUR" }).hits).toEqual([]);
  });
});
