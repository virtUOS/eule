import { afterEach, describe, expect, it, vi } from "vitest";

import type { ThemeConfig } from "../src/protocol";
import { applyTheme, resolveScheme } from "../src/theme";

function theme(light: Record<string, string>): ThemeConfig {
  return { dark_mode: "light", light, dark: {}, radius: {} };
}

describe("applyTheme (security #3)", () => {
  it("applies only --* custom properties, never real CSS properties", () => {
    const host = document.createElement("div");
    applyTheme(
      host,
      theme({
        "--primary": "#a6093d",
        background: "url(https://attacker.example/beacon)", // must be ignored
        "behavior": "url(#x)", // must be ignored
      }),
      "light",
    );
    expect(host.style.getPropertyValue("--primary")).toBe("#a6093d");
    expect(host.style.getPropertyValue("background")).toBe("");
    expect(host.style.background).toBe("");
    expect(host.style.getPropertyValue("behavior")).toBe("");
  });

  it("rejects malformed custom-property keys", () => {
    const host = document.createElement("div");
    applyTheme(host, theme({ "--ok": "1px", "--bad;background:red": "x" }), "light");
    expect(host.style.getPropertyValue("--ok")).toBe("1px");
    expect(host.style.getPropertyValue("--bad;background:red")).toBe("");
  });
});

describe("resolveScheme", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns a forced scheme without consulting the OS", () => {
    expect(resolveScheme("light")).toBe("light");
    expect(resolveScheme("dark")).toBe("dark");
  });

  it("auto follows prefers-color-scheme", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("dark") }));
    expect(resolveScheme("auto")).toBe("dark");
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    expect(resolveScheme("auto")).toBe("light");
  });
});
