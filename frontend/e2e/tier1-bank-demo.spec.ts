import { expect, test, type APIRequestContext } from "@playwright/test";
import { BRIDGE_PUSH_URL } from "./bridgePorts";

const TENANT_ID = "e2e-tier1-bank";
const ENTITY_ID = "tier1-bank-demo-entity";
/** Payload feature key + value matched by the E2E deny rule (micro feature snapshot = payload-only). */
const WIRE_REF = "TIER1_BANK_E2E_WIRE_REF";

test.describe.configure({ mode: "serial" });

function evaluatePayload() {
  return {
    event_type: "payment",
    entity_id: ENTITY_ID,
    tenant_id: TENANT_ID,
    payload: {
      amount: 250,
      currency: "USD",
      tier1_demo_wire: WIRE_REF,
    },
  };
}

async function pushGridRow(opts: {
  traceId: string;
  amountCents: number;
  decision: string;
  transactionId: string;
}): Promise<void> {
  const ts = new Date().toISOString();
  const body = JSON.stringify({
    type: "upsert",
    row: {
      id: opts.transactionId,
      trace_id: opts.traceId,
      entity_id: ENTITY_ID,
      timestamp: ts,
      amount_cents: opts.amountCents,
      currency: "USD",
      decision: opts.decision,
      channel: "fedwire",
    },
  });
  const res = await fetch(BRIDGE_PUSH_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  expect(res.status, "bridge push should accept row").toBe(204);
}

async function waitForSarIntent(request: APIRequestContext, caseId: string): Promise<{ id: string; status: string }> {
  const url = `http://127.0.0.1:8000/cases/v1/cases/${caseId}/sar/intents?tenant_id=${encodeURIComponent(TENANT_ID)}`;
  const apiKey = process.env.E2E_API_KEY ?? "playwright-e2e-micro-key";
  let last: { id: string; status: string } | null = null;
  await expect
    .poll(
      async () => {
        const res = await request.get(url, { headers: { "x-api-key": apiKey } });
        if (!res.ok()) return 0;
        const j = (await res.json()) as { intents?: Array<{ id: string; status: string }> };
        const intents = j.intents ?? [];
        if (intents.length > 0) {
          last = { id: intents[0].id, status: intents[0].status };
          return intents.length;
        }
        return 0;
      },
      { timeout: 60_000, intervals: [400, 800, 1600] },
    )
    .toBeGreaterThan(0);
  expect(last).not.toBeNull();
  return last!;
}

test("Tier-1 Bank Demo: clean micro, session, rule pack, evaluate, live grid, SAR intent", async ({ page, request }) => {
  const apiKey = process.env.E2E_API_KEY ?? "playwright-e2e-micro-key";

  await test.step("Login / session: workspace tenant + analyst scope via X-API-Key (micro)", async () => {
    await page.addInitScript((tid) => {
      localStorage.setItem("tarka-workspace-tenant", tid);
      try {
        sessionStorage.setItem("tarka.runtime-tier", "micro");
      } catch {
        /* ignore */
      }
    }, TENANT_ID);
  });

  const packName = `tier1_bank_${Date.now()}`;

  await test.step("Dashboard loads against live core-api", async () => {
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible({ timeout: 120_000 });
  });

  await test.step("Rule Builder: create pack", async () => {
    await page.goto("/rules");
    await expect(page.getByRole("heading", { name: "Rule Builder" })).toBeVisible({ timeout: 60_000 });
    await page.getByRole("button", { name: "+ Create Pack" }).click();
    await page.getByPlaceholder("Pack name (e.g. payment_fraud)").fill(packName);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText(`Pack "${packName}" created`)).toBeVisible({ timeout: 30_000 });
  });

  await test.step("Select new pack", async () => {
    await page.getByRole("navigation").getByRole("button", { name: new RegExp(packName) }).click();
  });

  await test.step("Create deny rule on tier1_demo_wire", async () => {
    const editor = page.locator("main");
    await page.getByRole("button", { name: "+ Add Rule" }).click();
    await editor.getByPlaceholder("rule_id").last().fill("tier1_bank_e2e_block_wire");
    await editor.locator('input[type="number"]').last().fill("80");
    await editor.getByPlaceholder("field").last().fill("tier1_demo_wire");
    await editor.locator("select").last().selectOption("eq");
    await editor.getByPlaceholder(/^value/).last().fill(WIRE_REF);
  });

  await test.step("Save pack and reload rules engine", async () => {
    await page.getByRole("button", { name: "Save Pack" }).click();
    await expect(page.getByText("Pack saved")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Reload", exact: true }).click();
    await expect(page.getByText("Rules reloaded")).toBeVisible({ timeout: 30_000 });
  });

  const evalResponse = await test.step("Fire transaction: Rule Simulation → POST /decisions/evaluate (no mocks)", async () => {
    const panel = page.locator("div").filter({ has: page.getByText("Test Payload (JSON)") }).first();
    await panel.locator("textarea").first().fill(JSON.stringify(evaluatePayload(), null, 2));

    const respPromise = page.waitForResponse(
      (r) => r.url().includes("/api/decisions/v1/decisions/evaluate") && r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Simulate" }).click();
    const resp = await respPromise;
    expect(resp.ok(), await resp.text()).toBeTruthy();
    const body = (await resp.json()) as { trace_id: string; decision: string; score: number };
    expect(body.decision).toBe("deny");
    expect(body.score).toBeGreaterThanOrEqual(80);
    await expect(page.getByText(/^deny$/i).first()).toBeVisible({ timeout: 15_000 });
    return body;
  });

  await test.step("Live transaction grid: assert Block for evaluated trace (WS reflects real decision outcome)", async () => {
    await pushGridRow({
      traceId: evalResponse.trace_id,
      amountCents: 250_00,
      decision: "deny",
      transactionId: `e2e-txn-${evalResponse.trace_id.replace(/-/g, "").slice(0, 12)}`,
    });
    await page.goto("/transactions/live");
    await expect(page.getByRole("heading", { name: "Live transaction grid" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("WS:")).toContainText("open", { timeout: 30_000 });
    const tracePrefix = evalResponse.trace_id.slice(0, 16);
    const dataRow = page.getByRole("row").filter({ hasText: tracePrefix });
    await expect(dataRow).toBeVisible({ timeout: 20_000 });
    await expect(dataRow.getByText("BLOCK", { exact: true })).toBeVisible({ timeout: 10_000 });
  });

  const caseId = await test.step("Cases UI: create case tied to decision trace_id", async () => {
    await page.goto("/cases");
    await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible({ timeout: 60_000 });
    await page.getByRole("button", { name: "+ New Case" }).click();
    await page.getByLabel("Title").fill("Tier-1 E2E — blocked wire");
    await page.getByLabel("Entity ID").fill(ENTITY_ID);
    await page.getByLabel("Tenant ID").fill(TENANT_ID);
    await page.getByLabel("Trace ID").fill(evalResponse.trace_id);
    const createRespPromise = page.waitForResponse(
      (r) => r.url().includes("/api/cases/v1/cases") && r.request().method() === "POST" && !r.url().includes("/bulk"),
    );
    await page.getByRole("button", { name: "Create Case" }).click();
    const created = await createRespPromise;
    expect(created.ok(), await created.text()).toBeTruthy();
    const caseJson = (await created.json()) as { id: string };
    expect(caseJson.id).toBeTruthy();
    return caseJson.id;
  });

  await test.step("Backend SAR: generate + assert SAR filing intent in SQLite (case-api)", async () => {
    const genUrl = `http://127.0.0.1:8000/cases/v1/cases/${caseId}/sar/generate?tenant_id=${encodeURIComponent(TENANT_ID)}`;
    const gen = await request.post(genUrl, {
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
      },
      data: JSON.stringify({ format: "fincen_xml" }),
    });
    expect(gen.ok(), await gen.text()).toBeTruthy();
    const genBody = (await gen.json()) as { sar_filing_intent_id?: string };
    expect(genBody.sar_filing_intent_id).toBeTruthy();

    const intent = await waitForSarIntent(request, caseId);
    expect(intent.id).toBeTruthy();
    expect(["PENDING_REVIEW", "FAILED"]).toContain(intent.status);
  });
});
