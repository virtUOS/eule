import { expect, test } from "@playwright/test";

import { stubBackend, waitReady } from "./fixtures";

// Batch 5b — retry_after backoff + post-done ghost-bubble guard.

async function sendMessage(page: import("@playwright/test").Page, text: string): Promise<void> {
  const input = page.locator(".cb-input");
  await input.fill(text);
  await input.press("Enter");
}

test.beforeEach(async ({ page }) => {
  await stubBackend(page);
});

test("429 retry_after disables the retry button until the window passes", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  // 429 with a 1s back-off (registered after stubBackend → wins)
  await page.route("**/api/v1/bots/*/chat", (route) =>
    route.fulfill({
      status: 429,
      contentType: "application/json",
      body: JSON.stringify({
        type: "error", code: "rate_limited", message: "Too many requests.",
        recoverable: true, retry_after: 1,
      }),
    }),
  );

  await sendMessage(page, "hi");
  const retry = page.locator(".cb-error button");
  await expect(page.locator(".cb-error")).toBeVisible();
  await expect(retry).toBeVisible();
  await expect(retry).toBeDisabled(); // within the back-off window
  await expect(retry).toBeEnabled({ timeout: 2000 }); // re-enables after ~1s
});

test("events after the terminal done are ignored (no ghost bubble)", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  // a misbehaving server: an extra text event AFTER done
  const body =
    'event: session\ndata: {"type":"session","seq":0,"session_id":"sess-e2e","protocol_version":"1.1","bot_id":"echo","expires_in":1800}\n\n' +
    'event: text\ndata: {"type":"text","seq":1,"message_id":"m1","delta":"Real answer."}\n\n' +
    'event: done\ndata: {"type":"done","seq":2,"status":"complete","session_id":"sess-e2e","expires_in":1800}\n\n' +
    'event: text\ndata: {"type":"text","seq":3,"message_id":"m2","delta":"GHOST"}\n\n';
  await page.route("**/api/v1/bots/*/chat", (route) =>
    route.fulfill({ contentType: "text/event-stream", body }),
  );

  await sendMessage(page, "hi");
  await expect(page.locator(".cb-bot-body")).toHaveText("Real answer.");
  await expect(page.locator(".cb-bot-body")).toHaveCount(1); // the ghost m2 bubble never rendered
  await expect(page.locator(".cb-bot-body")).not.toContainText("GHOST");
});
