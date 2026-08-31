import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const src = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "CaseDetail.tsx"), "utf8");

describe("Case Entity Graph overlay", () => {
  it("embeds the object dossier so it cannot cover the canvas", () => {
    const graphTab = src.slice(src.indexOf("function GraphTab"));
    expect(graphTab).toContain("embedded");
    expect(graphTab).not.toContain('role="dialog"');
  });
});
