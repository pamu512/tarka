import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const conf = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../nginx.conf"), "utf8");

describe("production nginx hops", () => {
  it("proxies SPA paths that used to fall through to index.html", () => {
    expect(conf).toContain("location /api/orchestrator/");
    expect(conf).toContain("location /api/v1/demo/");
    expect(conf).toContain("location /api/collab/");
    expect(conf).toContain("location /graphql");
    expect(conf).toContain("orchestrator:8790");
    expect(conf).toContain("investigation-agent:8006");
    expect(conf).toContain("graphql-gateway:8010");
    expect(conf).toContain("upstream_unavailable");
  });

  it("does not route analytics at the retired data-platform :8014 listener", () => {
    expect(conf).not.toContain("8014");
    expect(conf).not.toContain("data-platform");
    expect(conf).toContain("data-plane:8007");
  });
});
