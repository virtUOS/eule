import { expect, test } from "@playwright/test";

import { CONFIG } from "./fixtures";

// Step 3 (widget side): token_expired → getToken() refresh + automatic single retry.

test("token_expired triggers a getToken refresh and the retried turn succeeds", async ({ page }) => {
  // getToken returns an expired token first, then a fresh one on refresh.
  await page.addInitScript(() => {
    let n = 0;
    (window as unknown as { __tok: () => string }).__tok = () => (n++ === 0 ? "expired" : "fresh");
  });

  await page.route("**/api/v1/bots/*/config*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(CONFIG) }),
  );

  let expiredHits = 0;
  let freshHits = 0;
  await page.route("**/api/v1/bots/*/chat", (route) => {
    const auth = route.request().headers()["authorization"];
    if (auth === "Bearer expired") {
      expiredHits += 1;
      return route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ type: "error", code: "token_expired", message: "expired", recoverable: true }),
      });
    }
    freshHits += 1;
    return route.fulfill({
      contentType: "text/event-stream",
      body:
        'event: session\ndata: {"type":"session","seq":0,"session_id":"s","protocol_version":"1.0","bot_id":"echo","expires_in":1800}\n\n' +
        'event: text\ndata: {"type":"text","seq":1,"message_id":"m1","delta":"authenticated answer"}\n\n' +
        'event: done\ndata: {"type":"done","seq":2,"status":"complete","session_id":"s"}\n\n',
    });
  });

  await page.goto("/?mode=inline&lang=en&getToken=__tok");
  await page.waitForFunction(() => document.body.dataset.ready === "1");

  await page.locator(".cb-input").fill("hello");
  await page.locator(".cb-input").press("Enter");

  // the refreshed retry rendered the answer, and the error banner never stuck
  await expect(page.locator(".cb-bot-body")).toContainText("authenticated answer");
  await expect(page.locator(".cb-error")).toBeHidden();
  expect(expiredHits).toBe(1); // first attempt used the expired token
  expect(freshHits).toBe(1); // exactly one refreshed retry
});
