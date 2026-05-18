/**
 * Node is required: real `http.Server` + real `fetch` to localhost (health is not mocked).
 * @vitest-environment node
 */
import * as http from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";

import { ApolloClient, gql, HttpLink, InMemoryCache } from "@apollo/client";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { registerDataCaches, unregisterDataCaches } from "@/lib/dataCachesRegistry";
import {
  resetRuntimeEnvironmentStoreForTests,
  useRuntimeEnvironmentStore,
} from "@/state/runtimeEnvironmentStore";

const SEED_QUERY = gql`
  query RuntimeEnvSeed {
    __typename
  }
`;

function listen(server: http.Server): Promise<number> {
  return new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (addr && typeof addr === "object") {
        resolve(addr.port);
      } else {
        reject(new Error("Expected TCP address"));
      }
    });
    server.on("error", reject);
  });
}

function closeServer(server: http.Server): Promise<void> {
  return new Promise((resolve, reject) => {
    server.close((err: Error | undefined) => (err ? reject(err) : resolve()));
  });
}

describe("runtime environment tier transition", () => {
  let server: http.Server | null = null;

  beforeEach(() => {
    vi.unstubAllEnvs();
    unregisterDataCaches();
    resetRuntimeEnvironmentStoreForTests();
  });

  afterEach(async () => {
    vi.unstubAllEnvs();
    unregisterDataCaches();
    resetRuntimeEnvironmentStoreForTests();
    if (server) {
      await closeServer(server);
      server = null;
    }
  });

  it("purges TanStack Query + Apollo caches and performs a real HTTP health fetch when tier switches", async () => {
    let healthHits = 0;
    server = http.createServer((req: IncomingMessage, res: ServerResponse) => {
      if (req.method === "GET" && req.url?.startsWith("/health")) {
        healthHits += 1;
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, hit: healthHits }));
        return;
      }
      res.statusCode = 404;
      res.end();
    });
    const port = await listen(server);
    const healthUrl = `http://127.0.0.1:${port}/health`;
    vi.stubEnv("VITE_HEALTH_URL_MICRO", healthUrl);
    vi.stubEnv("VITE_HEALTH_URL_PRODUCTION", healthUrl);

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const apolloClient = new ApolloClient({
      link: new HttpLink({ uri: `http://127.0.0.1:${port}/graphql` }),
      cache: new InMemoryCache(),
    });
    apolloClient.cache.writeQuery({
      query: SEED_QUERY,
      data: { __typename: "Query" },
    });
    queryClient.setQueryData(["__tarka_runtime_env_seed__"], { seeded: true });

    const apolloBefore = Object.keys(apolloClient.cache.extract()).length;
    expect(apolloBefore).toBeGreaterThan(0);
    expect(queryClient.getQueryData(["__tarka_runtime_env_seed__"])).toEqual({ seeded: true });

    registerDataCaches({ queryClient, apolloClient });

    await useRuntimeEnvironmentStore.getState().setRuntimeTier("production");

    expect(useRuntimeEnvironmentStore.getState().tier).toBe("production");
    expect(healthHits).toBeGreaterThanOrEqual(1);
    expect(useRuntimeEnvironmentStore.getState().healthStatus).toBe("success");
    expect(useRuntimeEnvironmentStore.getState().healthSnapshot).toEqual(
      expect.objectContaining({ ok: true }),
    );

    expect(queryClient.getQueryData(["__tarka_runtime_env_seed__"])).toBeUndefined();
    expect(Object.keys(apolloClient.cache.extract()).length).toBe(0);
  });

  it("records health errors from a real non-2xx HTTP response without mocking fetch", async () => {
    server = http.createServer((req: IncomingMessage, res: ServerResponse) => {
      if (req.method === "GET" && req.url?.startsWith("/health")) {
        res.writeHead(503, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: false, reason: "overloaded" }));
        return;
      }
      res.statusCode = 404;
      res.end();
    });
    const port = await listen(server);
    const healthUrl = `http://127.0.0.1:${port}/health`;
    vi.stubEnv("VITE_HEALTH_URL_MICRO", healthUrl);
    vi.stubEnv("VITE_HEALTH_URL_PRODUCTION", healthUrl);

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const apolloClient = new ApolloClient({
      link: new HttpLink({ uri: `http://127.0.0.1:${port}/graphql` }),
      cache: new InMemoryCache(),
    });
    registerDataCaches({ queryClient, apolloClient });

    await useRuntimeEnvironmentStore.getState().setRuntimeTier("production");

    expect(useRuntimeEnvironmentStore.getState().healthStatus).toBe("error");
    expect(useRuntimeEnvironmentStore.getState().lastHealthHttpStatus).toBe(503);
    expect(useRuntimeEnvironmentStore.getState().healthSnapshot).toEqual(
      expect.objectContaining({ ok: false }),
    );
  });

  it("does not call the health server when the requested tier matches the current tier", async () => {
    let healthHits = 0;
    server = http.createServer((req: IncomingMessage, res: ServerResponse) => {
      if (req.method === "GET" && req.url?.startsWith("/health")) {
        healthHits += 1;
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true }));
        return;
      }
      res.statusCode = 404;
      res.end();
    });
    const port = await listen(server);
    const healthUrl = `http://127.0.0.1:${port}/health`;
    vi.stubEnv("VITE_HEALTH_URL_MICRO", healthUrl);
    vi.stubEnv("VITE_HEALTH_URL_PRODUCTION", healthUrl);

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const apolloClient = new ApolloClient({
      link: new HttpLink({ uri: `http://127.0.0.1:${port}/graphql` }),
      cache: new InMemoryCache(),
    });
    registerDataCaches({ queryClient, apolloClient });

    await useRuntimeEnvironmentStore.getState().setRuntimeTier("micro");
    expect(healthHits).toBe(0);
  });
});
