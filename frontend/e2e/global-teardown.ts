import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const statePath = path.join(__dirname, ".bridge-child.json");

export default async function globalTeardown(): Promise<void> {
  try {
    const raw = fs.readFileSync(statePath, "utf8");
    const { pid } = JSON.parse(raw) as { pid: number };
    if (pid > 0) {
      try {
        process.kill(pid, "SIGTERM");
      } catch {
        /* already dead */
      }
    }
  } catch {
    /* no state */
  }
  try {
    fs.unlinkSync(statePath);
  } catch {
    /* ignore */
  }
}
