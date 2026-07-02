import { expect, test } from "@playwright/test";

import { stubBackend, waitReady } from "./fixtures";

// Regression tests for code-review findings F2, F4, F7 (widget side).

test.beforeEach(async ({ page }) => {
  await stubBackend(page);
});

// F2 — sources are announced AFTER the message body (docs/05 §3), never before.
test("F2: sources announced after the body in the message live region", async ({ page }) => {
  await page.goto("/?mode=inline&lang=en");
  await waitReady(page);
  await page.locator(".cb-input").fill("vpn");
  await page.locator(".cb-input").press("Enter");
  await expect(page.locator(".cb-sources")).toBeVisible();

  const chunks = await page.locator("#cb-message-announcer > *").allTextContents();
  const sourcesIdx = chunks.findIndex((t) => /sources?:/i.test(t));
  expect(sourcesIdx).toBeGreaterThanOrEqual(0);
  // sources announcement is the LAST thing said, and the body was said before it
  expect(sourcesIdx).toBe(chunks.length - 1);
  expect(chunks.slice(0, sourcesIdx).join(" ")).toContain("short answer");
});

// F7 — a turn with two message_ids renders two bubbles; sources bind to the right one.
test("F7: two message_ids render two bubbles; sources bind to the first", async ({ page }) => {
  await page.goto("/?mode=inline&lang=en");
  await waitReady(page);
  await page.locator(".cb-input").fill("give me two");
  await page.locator(".cb-input").press("Enter");

  await expect(page.locator(".cb-bot-body")).toHaveCount(2);
  const bubbles = page.locator(".cb-msg:has(.cb-bot-body)");
  // sources footer is under the FIRST bot message only
  await expect(bubbles.nth(0).locator(".cb-sources")).toHaveCount(1);
  await expect(bubbles.nth(1).locator(".cb-sources")).toHaveCount(0);
  await expect(page.locator(".cb-bot-body").nth(0)).toContainText("First answer.");
  await expect(page.locator(".cb-bot-body").nth(1)).toContainText("Second answer.");
});

// F4 — a dropped RESUME turn is not offered as retryable (the interrupt is consumed).
test("F4: transport drop on a resume turn shows a non-recoverable error (no retry)", async ({ page }) => {
  await page.goto("/?mode=inline&lang=en");
  await waitReady(page);

  // reach an interrupt
  await page.locator(".cb-input").fill("show the menu");
  await page.locator(".cb-input").press("Enter");
  await expect(page.locator('.cb-chips[role="group"]')).toBeVisible();

  // make the NEXT (resume) request drop mid-stream: SSE with no terminal `done`
  await page.route("**/api/v1/bots/*/chat", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body:
        'event: session\ndata: {"type":"session","seq":0,"session_id":"s","protocol_version":"1.0","bot_id":"echo","expires_in":1800}\n\n' +
        'event: text\ndata: {"type":"text","seq":1,"message_id":"m1","delta":"partial"}\n\n',
    }),
  );

  await page.locator('.cb-chips[role="group"] button').first().click();

  await expect(page.locator(".cb-error")).toBeVisible();
  // retry button is hidden because a consumed interrupt cannot be safely retried
  await expect(page.locator(".cb-error button")).toBeHidden();
});

// Control: a dropped MESSAGE turn IS retryable (retry button shown).
test("F4 control: dropped message turn offers retry", async ({ page }) => {
  await page.goto("/?mode=inline&lang=en");
  await waitReady(page);
  await page.route("**/api/v1/bots/*/chat", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body:
        'event: session\ndata: {"type":"session","seq":0,"session_id":"s","protocol_version":"1.0","bot_id":"echo","expires_in":1800}\n\n' +
        'event: text\ndata: {"type":"text","seq":1,"message_id":"m1","delta":"partial"}\n\n',
    }),
  );
  await page.locator(".cb-input").fill("hello");
  await page.locator(".cb-input").press("Enter");
  await expect(page.locator(".cb-error")).toBeVisible();
  await expect(page.locator(".cb-error button")).toBeVisible();
});
