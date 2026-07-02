import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { stubBackend, waitReady } from "./fixtures";

// T10-A — automated axe-core, zero violations in each state (docs/05 §11).

test.beforeEach(async ({ page }) => {
  await stubBackend(page);
});

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function axe(page: import("@playwright/test").Page) {
  // Analyze against the WCAG 2.1 AA mandate (docs/05 §1); axe descends into open
  // shadow roots. (Best-practice-only rules like landmark-region are out of the
  // legal target and would flag the host demo page, not the widget.)
  return new AxeBuilder({ page }).withTags(WCAG).analyze();
}

test("idle (inline) has no violations", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await expect(page.locator(".cb-chip").first()).toBeVisible(); // starter chips
  const results = await axe(page);
  expect(results.violations).toEqual([]);
});

test("sources-shown has no violations", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await page.locator(".cb-input").fill("vpn");
  await page.locator(".cb-input").press("Enter");
  await expect(page.locator(".cb-sources")).toBeVisible();
  const results = await axe(page);
  expect(results.violations).toEqual([]);
});

test("quick-replies (interrupt) has no violations", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await page.locator(".cb-input").fill("show me the menu");
  await page.locator(".cb-input").press("Enter");
  await expect(page.locator('.cb-chips[role="group"]')).toBeVisible();
  const results = await axe(page);
  expect(results.violations).toEqual([]);
});

test("disabled composer has no violations", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await page.locator(".cb-input").fill("locked flow");
  await page.locator(".cb-input").press("Enter");
  await expect(page.locator(".cb-input")).toBeDisabled();
  const results = await axe(page);
  expect(results.violations).toEqual([]);
});

test("launcher (overlay dialog) open has no violations", async ({ page }) => {
  await page.goto("/?mode=launcher");
  await waitReady(page);
  await page.locator(".cb-launcher").click();
  await expect(page.locator('.cb-panel[role="dialog"]')).toBeVisible();
  const results = await axe(page);
  expect(results.violations).toEqual([]);
});

test("standalone page has no violations", async ({ page }) => {
  await page.goto("/standalone.html");
  await waitReady(page);
  const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  expect(results.violations).toEqual([]);
});
