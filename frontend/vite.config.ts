import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
          if (id.includes("vis-network") || id.includes("vis-data")) {
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
    },
  },
});
