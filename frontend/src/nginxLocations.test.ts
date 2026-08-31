import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const conf = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../nginx.conf"), "utf8");

describe("production nginx hops", () => {
  it("proxies SPA paths that used to fall through to index.html", () => {
    expect(conf).toContain("location /api/auth/");
    expect(conf).toContain("core-api:8000");
    expect(conf).toContain("rewrite ^/api/auth/(.*)$ /auth/$1 break;");
    expect(conf).toContain("location /api/orchestrator/");
    expect(conf).toContain("location /api/v1/demo/");
    expect(conf).toContain("location /api/collab/");
    expect(conf).toContain("location /graphql");
    expect(conf).toContain("orchestrator:8790");
    expect(conf).toContain("investigation-agent:8006");
    expect(conf).toContain("signal-api:8004");
    expect(conf).toContain("integration-ingress:8003");
    expect(conf).toContain("graphql-gateway:8010");
    expect(conf).toContain("upstream_unavailable");
    expect(conf).toContain("set $tarka_optional signal-api:8004");
    expect(conf).toContain("set $tarka_optional integration-ingress:8003");
  });

  it("rewrites /api/graph to graph-service /v1", () => {
    expect(conf).toContain("location /api/graph/");
    expect(conf).toContain("graph-service:8001");
    expect(conf).toContain("rewrite ^/api/graph/(.*)$ /$1 break;");
  });

  it("does not route analytics at the retired data-platform :8014 listener", () => {
    expect(conf).not.toContain("8014");
    expect(conf).not.toContain("data-platform");
    expect(conf).toContain("data-plane:8007");
  });
});
