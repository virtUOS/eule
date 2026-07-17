import { expect, test } from "@playwright/test";

import { stubBackend, waitReady } from "./fixtures";

// Step 13 — the `actions` event: contact/link buttons rendered as real links, with
// unsafe values dropped, and restored on reload.

async function sendMessage(page: import("@playwright/test").Page, text: string): Promise<void> {
  const input = page.locator(".cb-input");
  await input.fill(text);
  await input.press("Enter");
}

test.beforeEach(async ({ page }) => {
  await stubBackend(page);
});

test("actions render as links; tel is a tel: href; unsafe url is dropped", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await sendMessage(page, "contact please");

  await expect(page.locator(".cb-bot-body")).toContainText("Reach us here.");
  const actions = page.locator(".cb-action");
  await expect(actions).toHaveCount(2); // javascript: url dropped

  const tel = page.locator('.cb-action[href^="tel:"]');
  await expect(tel).toHaveAttribute("href", "tel:+495419690000"); // spaces stripped
  await expect(tel).toContainText("IT-Service-Desk");
  await expect(tel).toContainText("+49 541 969 0000"); // number shown for desktop

  await expect(page.locator('.cb-action[href="https://good.example/portal"]')).toBeVisible();
  await expect(page.locator('.cb-action[href^="javascript:"]')).toHaveCount(0);
});

test("actions survive a reload", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await sendMessage(page, "contact please");
  await expect(page.locator(".cb-action")).toHaveCount(2);

  await page.reload();
  await stubBackend(page);
  await waitReady(page);
  await expect(page.locator(".cb-bot-body")).toContainText("Reach us here.");
  await expect(page.locator('.cb-action[href^="tel:"]')).toHaveAttribute("href", "tel:+495419690000");
  await expect(page.locator(".cb-action")).toHaveCount(2);
});
