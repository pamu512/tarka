import { expect, test } from "@playwright/test";

/**
 * Mock-free QA desk smoke. Opt-in: needs case-api + frontend with
 * VITE_USE_API_MOCKS=false (playwright.config already sets false).
 * Set E2E_QA_DESK=1 to enable (skipped by default in CI without stack).
 */
const enabled = process.env.E2E_QA_DESK === "1";

test.describe("ops QA desk (mock-free)", () => {
  test.skip(!enabled, "Set E2E_QA_DESK=1 when case-api is up");

  test("loads /ops/qa and shows sampling controls", async ({ page }) => {
    await page.goto("/ops/qa");
    await expect(page.getByText(/QA sampling desk/i)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: /Sample closed cases/i })).toBeVisible();
  });
});
