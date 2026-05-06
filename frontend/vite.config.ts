import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (id.includes("recharts") || id.includes("d3-")) {
            return "vendor-charts";
          }
          if (
            id.includes("vis-network") ||
            id.includes("vis-data") ||
            id.includes("react-force-graph") ||
            id.includes("force-graph") ||
            id.includes("three-forcegraph") ||
            id.includes("/d3-force") ||
            id.includes("/d3-quadtree") ||
            id.includes("/d3-binarytree")
          ) {
            return "vendor-graph";
          }
          if (id.includes("@xyflow")) {
            return "vendor-flow";
          }
          return;
        },
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/api/decisions": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/decisions/, "/decisions"),
      },
      "/api/cases": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/cases/, "/cases"),
      },
      /** Core API (macroservice): omni-search and other root ``/v1`` routes. */
      "/api/core": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/core/, ""),
      },
      /** Investor pitch: deterministic demo burst (hidden; maps to core-api ``POST /v1/internal/demo-burst``). */
      "/api/v1/internal/demo-burst": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: () => "/v1/internal/demo-burst",
      },
      "/api/graph": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/graph/, ""),
      },
      "/api/features": {
        target: "http://localhost:8004",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/features/, "/features"),
      },
      /** Signal API root (health + Prometheus); features/ml mount under /features and /ml. */
      "/api/signal-plane": {
        target: "http://localhost:8004",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/signal-plane/, ""),
      },
      "/api/ml": {
        target: "http://localhost:8004",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/ml/, "/ml"),
      },
      "/api/analytics": {
        target: "http://localhost:8007",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/analytics/, ""),
      },
      /** integration-ingress (local); production nginx uses ``/api/ingress/`` → integration-ingress. */
      "/api/ingress": {
        target: "http://localhost:8003",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/ingress/, ""),
      },
      "/api/investigation": {
        target: "http://localhost:8006",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/investigation/, ""),
      },
      "/api/ingest": {
        target: "http://localhost:8007",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/ingest/, ""),
      },
      /** Local Shadow sidecar (fraud copilot LLM); default port 8742 — see tools/shadow docs. */
      "/api/shadow-llm": {
        target: "http://127.0.0.1:8742",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/shadow-llm/, "/api"),
      },
    },
  },
});
