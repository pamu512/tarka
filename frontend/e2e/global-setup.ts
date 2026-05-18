/**
 * Playwright global setup:
 * - When `E2E_MANAGE_MICRO=1`, wipes `.tarka-micro-e2e/data` and starts Docker Micro with `docker-compose.micro.e2e.yml`.
 * - Otherwise assumes core-api is already up on port 8000.
 * - Starts the local WS bridge for `/transactions/live` (see `e2e/support/transactions-ws-bridge.mjs`).
 */
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { BRIDGE_HTTP_PORT, BRIDGE_WS_PORT } from "./bridgePorts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const bridgeScript = path.join(__dirname, "support/transactions-ws-bridge.mjs");
const statePath = path.join(__dirname, ".bridge-child.json");

async function waitForUrl(url: string, attempts = 80): Promise<void> {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (res.ok) return;
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`Timeout waiting for ${url}`);
}

export default async function globalSetup(): Promise<void> {
  const manageMicro = process.env.E2E_MANAGE_MICRO === "1";
  if (manageMicro) {
    execFileSync("bash", [path.join(repoRoot, "scripts/e2e/reset-micro-for-playwright.sh")], {
      stdio: "inherit",
      env: {
        ...process.env,
        E2E_API_KEY: process.env.E2E_API_KEY ?? "playwright-e2e-micro-key",
      },
    });
  }

  await waitForUrl("http://127.0.0.1:8000/v1/health");

  const child = spawn(process.execPath, [bridgeScript, String(BRIDGE_WS_PORT), String(BRIDGE_HTTP_PORT)], {
    detached: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (!child.pid) {
    throw new Error("Failed to spawn transactions WS bridge");
  }
  fs.writeFileSync(
    statePath,
    JSON.stringify({ pid: child.pid, wsPort: BRIDGE_WS_PORT, httpPort: BRIDGE_HTTP_PORT }),
    "utf8",
  );
  child.stdout?.on("data", () => {});
  child.stderr?.on("data", () => {});
  child.unref();

  await waitForUrl(`http://127.0.0.1:${BRIDGE_HTTP_PORT}/health`);
}
