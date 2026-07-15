import { expect, test } from "@playwright/test";

import { stubBackend, waitReady } from "./fixtures";

// Step 8 — host-page context passthrough (docs/01 §Context). The widget forwards
// the configured context object on every turn; it is metadata, never an input.

test.beforeEach(async ({ page }) => {
  await stubBackend(page);
});

async function sendMessage(page: import("@playwright/test").Page, text: string): Promise<void> {
  const input = page.locator(".cb-input");
  await input.fill(text);
  await input.press("Enter");
}

test("configured context rides every message turn", async ({ page }) => {
  await page.goto("/?mode=inline&topic=admissions&page=https%3A%2F%2Fhost.example%2Finformatik");
  await waitReady(page);

  const [first] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/chat") && r.method() === "POST"),
    sendMessage(page, "hello"),
  ]);
  expect(first.postDataJSON().context).toEqual({
    topic: "admissions",
    page: "https://host.example/informatik",
  });
  await expect(page.locator(".cb-bot-body")).toContainText("Here is a short answer");

  // second turn carries it too (it's per-turn metadata, not first-turn-only)
  const [second] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/chat") && r.method() === "POST"),
    sendMessage(page, "again"),
  ]);
  expect(second.postDataJSON().context.topic).toBe("admissions");
});

test("context also rides a quick-reply resume turn", async ({ page }) => {
  await page.goto("/?mode=inline&topic=admissions");
  await waitReady(page);
  await sendMessage(page, "menu");
  const chip = page.locator(".cb-chip", { hasText: "Check credits" });
  await expect(chip).toBeVisible();

  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/chat") && r.method() === "POST"),
    chip.click(),
  ]);
  const body = request.postDataJSON();
  expect(body.choice).toEqual({ id: "credits" });
  expect(body.context).toEqual({ topic: "admissions" }); // gateway ignores it on resume
});

test("no context configured -> no context field on the wire", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/chat") && r.method() === "POST"),
    sendMessage(page, "hello"),
  ]);
  expect(request.postDataJSON().context).toBeUndefined();
});
