/**
 * End-to-end walk of the demo flow against a running stack (seeded with scripts/seed_demo.py --extract).
 * Analyst assertions need ANTHROPIC_API_KEY on the API; they are skipped otherwise.
 */
import { expect, test } from "@playwright/test";

const EMAIL = "buyer@kaveri.example";
const PASSWORD = process.env.DEMO_PASSWORD || "quoteiq-demo";

test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await page.getByPlaceholder("password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/dashboard/);
});

test("dashboard → comparison shows 30 lines and coverage warning", async ({ page }) => {
  await page.getByRole("link", { name: "Comparison" }).first().click();
  await expect(page.getByText("Bid comparison")).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(30);
  await expect(page.getByText(/not like-for-like/)).toBeVisible();
  await page.getByRole("button", { name: "Needs attention" }).click();
  expect(await page.locator("tbody tr").count()).toBeLessThan(30);
});

test("evidence drawer opens with calculation trace", async ({ page }) => {
  await page.getByRole("link", { name: "Comparison" }).first().click();
  await page.locator("tbody tr").first().locator("button").first().click();
  await expect(page.getByText("Calculation trace")).toBeVisible();
  await expect(page.getByText("Source evidence")).toBeVisible();
});

test("award: discount-aware split and approval guard", async ({ page }) => {
  await page.getByRole("link", { name: "Award" }).first().click();
  await page.getByRole("button", { name: /Lowest price, discount-aware/ }).click();
  await expect(page.getByText("Line allocation")).toBeVisible();
  await page.getByPlaceholder(/Approval note/).fill("E2E test approval attempt");
  await page.getByRole("button", { name: "Approve award" }).click();
  await expect(page.getByText(/verification|Approved/)).toBeVisible();
});

test("reports: comparison xlsx downloads", async ({ page }) => {
  await page.getByRole("link", { name: "Reports" }).click();
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Generate" }).first().click();
  expect((await dl).suggestedFilename()).toMatch(/comparison.*\.xlsx$/);
});

test("analyst answers the VP question with tool calls", async ({ page, request }) => {
  const health = await (await request.get((process.env.API_URL || "http://localhost:8000") + "/api/health")).json();
  test.skip(!health.ai_enabled, "ANTHROPIC_API_KEY not configured on API");
  await page.getByRole("link", { name: "AI Analyst" }).click();
  await page.getByPlaceholder(/What if we split/).fill("What if we split it, cheapest per line, but only among vendors who cleared the quality questionnaire?");
  await page.keyboard.press("Enter");
  await expect(page.getByText(/tool call\(s\)/)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/optimize_split_award/)).toBeVisible();
});
