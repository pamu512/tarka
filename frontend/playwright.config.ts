import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";
import { BRIDGE_WS_URL } from "./e2e/bridgePorts";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));

const E2E_API_KEY = process.env.E2E_API_KEY ?? "playwright-e2e-micro-key";
const devPort = 4173;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: `http://127.0.0.1:${devPort}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    extraHTTPHeaders: {
      "x-api-key": E2E_API_KEY,
    },
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${devPort}`,
    cwd: frontendDir,
    url: `http://127.0.0.1:${devPort}/`,
    reuseExistingServer: process.env.E2E_REUSE_DEV_SERVER === "1",
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
    env: {
      ...process.env,
      VITE_USE_API_MOCKS: "false",
      VITE_API_KEY: E2E_API_KEY,
      VITE_HEALTH_URL_MICRO: "http://127.0.0.1:8000/v1/health",
      VITE_TRANSACTIONS_WS_URL: BRIDGE_WS_URL,
    },
  },
});
