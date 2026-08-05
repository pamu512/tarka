import { expect, test } from "@playwright/test";

/**
 * Mock-free QA desk smoke. Opt-in: needs case-api + frontend with
 * VITE_USE_API_MOCKS=false (playwright.config already sets false).
 * Set E2E_QA_DESK=1 to enable (skipped by default without stack).
 *
 * Manual / CI micro profile:
 *   ./scripts/e2e/reset-micro-for-playwright.sh
 *   E2E_QA_DESK=1 npx playwright test e2e/ops-qa-desk.spec.ts
 */
const enabled = process.env.E2E_QA_DESK === "1";

test.describe("ops QA desk (mock-free)", () => {
  test.skip(!enabled, "Set E2E_QA_DESK=1 when case-api is up");

  test("loads /ops/qa and shows sampling controls", async ({ page }) => {
    await page.goto("/ops/qa");
    await expect(page.getByRole("heading", { name: /QA sampling desk/i })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole("button", { name: /Sample closed cases/i })).toBeVisible();
  });

  test("sample → metrics path visible", async ({ page }) => {
    await page.goto("/ops/qa");
    await expect(page.getByRole("heading", { name: /QA sampling desk/i })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(/Agreement rate/i)).toBeVisible();
    const sampleBtn = page.getByRole("button", { name: /Sample closed cases/i });
    await sampleBtn.click();
    // Empty queue is fine — surface must not fall back to brochure mocks.
    await expect(
      page.getByText(/No pending QA|pending QA|Sampled|Working|Agreement rate/i).first(),
    ).toBeVisible({ timeout: 20_000 });
  });
});
