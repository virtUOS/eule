import { expect, test } from "@playwright/test";

import { stubBackend, waitReady } from "./fixtures";

// Step 7 — survive-reload persistence. The widget stores session_id + transcript in
// localStorage and rehydrates on reload, continuing the SAME server session.

test.beforeEach(async ({ page }) => {
  await stubBackend(page);
});

async function sendMessage(page: import("@playwright/test").Page, text: string): Promise<void> {
  const input = page.locator(".cb-input");
  await input.fill(text);
  await input.press("Enter");
}

test("transcript and session survive a reload; next turn reuses the session id", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await sendMessage(page, "vpn please");
  await expect(page.locator(".cb-bot-body")).toContainText("Here is a short answer");
  await expect(page.locator(".cb-cite-title").first()).toContainText("VPN-Einrichtung");

  await page.reload();
  await stubBackend(page); // re-arm route interception after reload
  await waitReady(page);

  // rehydrated: user bubble, bot text, and the sources footer are back
  await expect(page.locator(".cb-user-bubble")).toContainText("vpn please");
  await expect(page.locator(".cb-bot-body")).toContainText("Here is a short answer");
  await expect(page.locator(".cb-cite-title").first()).toContainText("VPN-Einrichtung");
  // starters are NOT shown over a restored conversation
  await expect(page.locator(".cb-chip")).toHaveCount(0);

  // the next turn continues the SAME server session
  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/chat") && r.method() === "POST"),
    sendMessage(page, "follow-up"),
  ]);
  expect(request.postDataJSON().session_id).toBe("sess-e2e");
});

test("a pending interrupt (quick replies) is restored after reload and still answerable", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await sendMessage(page, "menu");
  await expect(page.locator(".cb-chip", { hasText: "Check credits" })).toBeVisible();

  await page.reload();
  await stubBackend(page);
  await waitReady(page);

  const chip = page.locator(".cb-chip", { hasText: "Check credits" });
  await expect(chip).toBeVisible();
  // rehydration must not steal focus on page load
  await expect(chip).not.toBeFocused();

  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/chat") && r.method() === "POST"),
    chip.click(),
  ]);
  const body = request.postDataJSON();
  expect(body.choice).toEqual({ id: "credits" });
  expect(body.reply_to).toBe("evt_1");
  expect(body.session_id).toBe("sess-e2e");
  await expect(page.locator(".cb-bot-body").last()).toContainText("You picked an option");
});

test("new chat clears the stored conversation", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await sendMessage(page, "hello");
  await expect(page.locator(".cb-bot-body")).toContainText("Here is a short answer");

  await page.getByRole("button", { name: /neu|new/i }).click();

  await page.reload();
  await stubBackend(page);
  await waitReady(page);
  await expect(page.locator(".cb-user-bubble")).toHaveCount(0);
  await expect(page.locator(".cb-chip").first()).toBeVisible(); // starters are back
});

test("an expired stored conversation is discarded on load", async ({ page }) => {
  await page.goto("/?mode=inline");
  await waitReady(page);
  await sendMessage(page, "hello");
  await expect(page.locator(".cb-bot-body")).toContainText("Here is a short answer");

  // force the client-side TTL mirror into the past
  await page.evaluate(() => {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key?.startsWith("cb:conv:")) continue;
      const conv = JSON.parse(localStorage.getItem(key) ?? "{}");
      conv.expiresAt = Date.now() - 1;
      localStorage.setItem(key, JSON.stringify(conv));
    }
  });

  await page.reload();
  await stubBackend(page);
  await waitReady(page);
  await expect(page.locator(".cb-user-bubble")).toHaveCount(0);
  await expect(page.locator(".cb-chip").first()).toBeVisible();
});
