import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(process.cwd(), "..", "..");
const openapiPath = resolve(root, "contracts", "openapi", "decision-api.yaml");
const tsPath = resolve(process.cwd(), "src", "index.ts");

const openapi = readFileSync(openapiPath, "utf8");
const tsSource = readFileSync(tsPath, "utf8");

const requiredTokens = [
  "integrity_confidence",
  "tamper_risk",
  "network_trust",
  "replay_risk",
  "geo_consistency_risk",
  "confidence_tier",
  "driver_reasons",
];

function hasTokenInOpenapi(token) {
  return openapi.includes(`${token}:`);
}

function hasTokenInTs(token) {
  return tsSource.includes(token);
}

const missing = [];
for (const token of requiredTokens) {
  if (!hasTokenInOpenapi(token)) {
    missing.push(`OpenAPI missing token: ${token}`);
  }
  if (!hasTokenInTs(token)) {
    missing.push(`TypeScript SDK missing token: ${token}`);
  }
}

if (missing.length) {
  console.error("Inference contract drift detected:");
  for (const row of missing) {
    console.error(`- ${row}`);
  }
  process.exit(1);
}

console.log("Inference contract tokens aligned (OpenAPI ↔ TypeScript SDK).");
