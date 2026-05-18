import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  graphAnnotationsStorageKey,
  loadGraphAnnotations,
  setGraphNodeAnnotation,
} from "./graphNodeAnnotations";

/** Vitest/jsdom localStorage can be unreliable; test persistence with an explicit memory backend. */
const memory: Record<string, string> = {};

describe("graphNodeAnnotations", () => {
  beforeEach(() => {
    for (const k of Object.keys(memory)) delete memory[k];
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => (k in memory ? memory[k] : null),
      setItem: (k: string, v: string) => {
        memory[k] = v;
      },
      removeItem: (k: string) => {
        delete memory[k];
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("round-trips notes per tenant + case", () => {
    setGraphNodeAnnotation("demo", "c1", "n1", "Known good");
    expect(loadGraphAnnotations("demo", "c1")).toEqual({ n1: "Known good" });
    expect(graphAnnotationsStorageKey("demo", "c1")).toContain("demo");
    expect(graphAnnotationsStorageKey("demo", "c1")).toContain("c1");
  });

  it("removes on empty text", () => {
    setGraphNodeAnnotation("demo", "c1", "n1", "x");
    setGraphNodeAnnotation("demo", "c1", "n1", "");
    expect(loadGraphAnnotations("demo", "c1")).toEqual({});
  });
});
