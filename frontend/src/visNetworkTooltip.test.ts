import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "index.css"), "utf8");

describe("vis-network tooltip", () => {
  it("never paints the vis-network title popup on the case graph", () => {
    expect(css).toContain("div.vis-tooltip");
    expect(css).toContain("display: none");
  });
});
