import { expect, test } from "@playwright/test";

import { stubBackend, waitReady } from "./fixtures";

// Host-configurable launcher offsets (offsetRight / offsetBottom → --cb-offset-*).
// Geometry is deterministic at a fixed viewport: launcher(58) + gap(14) = 72; the
// panel keeps a 28px top margin (offset + 72 + 28 = offset + 100). Uses an 800×600
// viewport (wide enough to avoid the <=480px full-bleed override).

const cs = (el: Element, prop: string) => getComputedStyle(el).getPropertyValue(prop);

test.beforeEach(async ({ page }) => {
  await stubBackend(page);
  await page.setViewportSize({ width: 800, height: 600 });
});

test("default offsets are unchanged (20px launcher, 92px panel, 480px height @600h)", async ({ page }) => {
  await page.goto("/?mode=launcher");
  await waitReady(page);

  const launcher = page.locator(".cb-launcher");
  expect(await launcher.evaluate(cs, "right")).toBe("20px");
  expect(await launcher.evaluate(cs, "bottom")).toBe("20px");

  await launcher.click(); // open the panel
  const panel = page.locator(".cb-panel");
  expect(await panel.evaluate(cs, "bottom")).toBe("92px"); // 20 + 72
  expect(await panel.evaluate(cs, "height")).toBe("480px"); // min(560, 600 - 20 - 100)
});

test("custom offsets apply and the panel height compensates", async ({ page }) => {
  await page.goto("/?mode=launcher&offsetRight=40px&offsetBottom=60px");
  await waitReady(page);

  const launcher = page.locator(".cb-launcher");
  expect(await launcher.evaluate(cs, "right")).toBe("40px");
  expect(await launcher.evaluate(cs, "bottom")).toBe("60px");

  await launcher.click();
  const panel = page.locator(".cb-panel");
  expect(await panel.evaluate(cs, "right")).toBe("40px"); // panel tracks the launcher
  expect(await panel.evaluate(cs, "bottom")).toBe("132px"); // 60 + 72
  // height shrinks by the extra 40px of bottom offset: 480 (default) → 440
  expect(await panel.evaluate(cs, "height")).toBe("440px"); // min(560, 600 - 60 - 100)
});

test("a calc()/max() expression is accepted", async ({ page }) => {
  // wolke's real value: align the launcher to a 1180px centered column.
  const expr = "max(24px, calc((100vw - 1180px) / 2 + 24px))";
  await page.goto(`/?mode=launcher&offsetRight=${encodeURIComponent(expr)}`);
  await waitReady(page);
  // at 800px wide the max() resolves to 24px (the calc term goes negative)
  expect(await page.locator(".cb-launcher").evaluate(cs, "right")).toBe("24px");
});

test("small-screen full-bleed ignores offsets", async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 700 });
  await page.goto("/?mode=launcher&offsetBottom=60px&offsetRight=40px");
  await waitReady(page);
  await page.locator(".cb-launcher").click();
  const panel = page.locator(".cb-panel");
  expect(await panel.evaluate(cs, "bottom")).toBe("0px"); // full-bleed, offset ignored
  expect(await panel.evaluate(cs, "right")).toBe("0px");
  // launcher is hidden while the panel is open on small screens
  await expect(page.locator(".cb-launcher")).toBeHidden();
});

test("a malicious offset value is rejected → default kept", async ({ page }) => {
  const evil = "20px;}body{display:none}";
  await page.goto(`/?mode=launcher&offsetRight=${encodeURIComponent(evil)}`);
  await waitReady(page);
  // rejected → the CSS default (20px) still applies, and nothing leaked into the page
  expect(await page.locator(".cb-launcher").evaluate(cs, "right")).toBe("20px");
  expect(await page.evaluate(() => getComputedStyle(document.body).display)).not.toBe("none");
});
