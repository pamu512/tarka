import { expect, test } from "@playwright/test";

/**
 * Optional live-desk walk for T1 / T4. Not a required CI check.
 * Skips when E2E_SCORECARD is unset or the desk has no leftover / decision rows.
 *
 *   E2E_SCORECARD=1 npx playwright test e2e/desk-ui-scorecard.spec.ts
 */
const optedIn = process.env.E2E_SCORECARD === "1";

test.describe("desk UI scorecard (live desk)", () => {
  test.skip(!optedIn, "manual/nightly; set E2E_SCORECARD=1 when the desk is up");

  test("T1 leftover REVIEW + receipt-why in one Open receipt click", async ({ page }) => {
    const res = await page.goto("/leftovers").catch(() => null);
    if (!res || !res.ok()) {
      test.skip(true, "desk down");
    }
    const open = page.getByRole("link", { name: /open receipt/i }).first();
    if ((await open.count()) === 0) {
      test.skip(true, "desk down or no leftover REVIEW");
    }
    await open.click();
    await expect(page.getByTestId("pack-why-strip")).toBeVisible({ timeout: 15_000 });
    const body = await page.locator("body").innerText();
    expect(body).toMatch(/REVIEW|review/);
    expect(body).not.toMatch(/(^|[^A-Z])FLAG([^A-Z]|$)/);
  });

  test("T4 Decisions row names the pack without opening a memorized UUID", async ({ page }) => {
    const res = await page.goto("/decisions").catch(() => null);
    if (!res || !res.ok()) {
      test.skip(true, "desk down");
    }
    const row = page.getByTestId(/decisions-row-/).first();
    if ((await row.count()) === 0) {
      test.skip(true, "desk down or no decisions");
    }
    await expect(row).toBeVisible({ timeout: 15_000 });
    const pack = row.getByTestId(/decisions-pack-/).first();
    if ((await pack.count()) === 0) {
      test.skip(true, "desk down or pack column missing");
    }
    const packText = ((await pack.textContent()) ?? "").trim();
    expect(packText.length).toBeGreaterThan(0);
    expect(packText).not.toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
  });
});
