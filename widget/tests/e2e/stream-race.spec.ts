import { expect, test } from "@playwright/test";

import { stubBackend, waitReady } from "./fixtures";

// Review batch 2 — one turn at a time + abortable streams + persist recovery.

const SLOW_SSE =
  'event: session\ndata: {"type":"session","seq":0,"session_id":"sess-e2e","protocol_version":"1.1","bot_id":"echo","expires_in":1800}\n\n' +
  'event: text\ndata: {"type":"text","seq":1,"message_id":"m1","delta":"Slow answer."}\n\n' +
  'event: done\ndata: {"type":"done","seq":2,"status":"complete","session_id":"sess-e2e","expires_in":1800}\n\n';

// Register AFTER stubBackend so this route wins (Playwright matches newest first):
// responds only after `delayMs`, giving the test a window where the turn is in flight.
async function slowChatRoute(page: import("@playwright/test").Page, delayMs: number, counter: { n: number }) {
  await page.route("**/api/v1/bots/*/chat", async (route) => {
    counter.n += 1;
    await new Promise((r) => setTimeout(r, delayMs));
    await route.fulfill({ contentType: "text/event-stream", body: SLOW_SSE });
  });
}

async function sendMessage(page: import("@playwright/test").Page, text: string): Promise<void> {
  const input = page.locator(".cb-input");
  await input.fill(text);
  await input.press("Enter");
}

test.beforeEach(async ({ page }) => {
  await stubBackend(page);
});

test("Enter during an in-flight turn does not fire a second request", async ({ page }) => {
  const counter = { n: 0 };
  await page.goto("/?mode=inline");
  await waitReady(page);
  await slowChatRoute(page, 500, counter);

  await sendMessage(page, "first");
  await sendMessage(page, "second"); // mid-flight: must be ignored, draft kept

  await expect(page.locator(".cb-bot-body")).toContainText("Slow answer.");
  expect(counter.n).toBe(1);
  // exactly one user bubble was appended; the blocked draft stays in the composer
  await expect(page.locator(".cb-user-bubble")).toHaveCount(1);
  await expect(page.locator(".cb-input")).toHaveValue("second");
});

// NOTE: starter-chip and quick-reply-chip double-fire races are structurally
// prevented — hideStarters()/clearInterrupt() remove the chips from the DOM
// synchronously on first activation. The `streaming` guards in sendMessage/
// sendChoice remain as belt-and-braces for future code paths.

test("new chat aborts the in-flight stream: no ghost text, no error banner", async ({ page }) => {
  const counter = { n: 0 };
  await page.goto("/?mode=inline");
  await waitReady(page);
  await slowChatRoute(page, 600, counter);

  await sendMessage(page, "will be cancelled");
  await page.getByRole("button", { name: /neu|new/i }).click(); // during the delay

  // wait past the delayed response; the aborted stream must not write anything
  await page.waitForTimeout(900);
  await expect(page.locator(".cb-bot-body")).toHaveCount(0);
  await expect(page.locator(".cb-user-bubble")).toHaveCount(0);
  await expect(page.locator(".cb-error")).toBeHidden(); // deliberate cancel ≠ connection lost
  // and the widget is usable again
  await expect(page.locator(".cb-chip").first()).toBeVisible();
});

test("a corrupt persisted blob is discarded — the widget still boots", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  // seed a blob whose element shapes are hostile (sources: [null])
  await page.evaluate(() => {
    localStorage.setItem(
      "cb:conv:v1:echo",
      JSON.stringify({
        v: 1,
        sessionId: "sess-x",
        expiresAt: Date.now() + 60_000,
        entries: [{ role: "bot", text: "x", sources: [null] }],
        pending: null,
      }),
    );
  });

  await page.reload();
  await stubBackend(page);
  await waitReady(page); // init must not reject
  await expect(page.locator(".cb-chip").first()).toBeVisible(); // fresh widget, starters shown
  // the poisoned slot was cleared, not left to fail again next load
  const cleared = await page.evaluate(() => localStorage.getItem("cb:conv:v1:echo"));
  expect(cleared).toBeNull();
});
