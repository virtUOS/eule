import { expect, test } from "@playwright/test";

import { stubBackend, waitReady } from "./fixtures";

// T10-B — keyboard-only operation (docs/05 §11), no mouse.

test.beforeEach(async ({ page }) => {
  await stubBackend(page);
});

test("full turn is completable by keyboard; focus returns to composer on done", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);

  const input = page.locator(".cb-input");
  await input.focus();
  await page.keyboard.type("vpn");
  await page.keyboard.press("Enter"); // send via Enter (docs/05 §7)

  await expect(page.locator(".cb-bot-body")).toContainText("Here is a short answer");
  await expect(page.locator(".cb-sources")).toBeVisible();
  // on complete, focus returns to the composer
  await expect(input).toBeFocused();
});

test("Shift+Enter inserts a newline instead of sending", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  const input = page.locator(".cb-input");
  await input.focus();
  await page.keyboard.type("line one");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.type("line two");
  await expect(input).toHaveValue("line one\nline two");
  await expect(page.locator(".cb-user-bubble")).toHaveCount(0); // nothing sent
});

test("interrupt moves focus to first choice; resolving returns focus to composer", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  const input = page.locator(".cb-input");
  await input.fill("menu please");
  await input.press("Enter");

  const firstChoice = page.locator('.cb-chips[role="group"] button').first();
  await expect(firstChoice).toBeFocused();

  // activate by keyboard
  await page.keyboard.press("Enter");
  await expect(page.locator(".cb-bot-body")).toContainText("You picked an option");
  await expect(input).toBeFocused();
});

test("disabled composer when allow_free_text is false, announced", async ({ page }) => {
  await page.goto("/?mode=inline&lang=en"); // language-stable assertion on the hint text
  await waitReady(page);
  await page.locator(".cb-input").fill("locked");
  await page.locator(".cb-input").press("Enter");
  await expect(page.locator(".cb-input")).toBeDisabled();
  await expect(page.locator("#cb-status-announcer")).toContainText(/choose/i);
});

test("launcher: Esc closes overlay and returns focus to the launcher", async ({ page }) => {
  await page.goto("/?mode=launcher");
  await waitReady(page);
  const launcher = page.locator(".cb-launcher");
  await launcher.click();
  await expect(page.locator('.cb-panel[role="dialog"]')).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(launcher).toBeFocused();
  await expect(launcher).toHaveAttribute("aria-expanded", "false");
});

test("focus is not stolen from the composer during streaming", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  const input = page.locator(".cb-input");
  await input.fill("vpn");
  await input.press("Enter");
  await expect(page.locator(".cb-bot-body")).toContainText("short answer");
  await expect(input).toBeFocused(); // never yanked to the log/message during a normal turn
});
