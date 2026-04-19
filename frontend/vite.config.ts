import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
        rewrite: (path) => path.replace(/^\/api\/decisions/, ""),
      },
      "/api/cases": {
        target: "http://localhost:8002",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/cases/, ""),
      },
      "/api/graph": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/graph/, ""),
      },
      "/api/ml": {
        target: "http://localhost:8005",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/ml/, ""),
      },
      "/api/analytics": {
        target: "http://localhost:8008",
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
