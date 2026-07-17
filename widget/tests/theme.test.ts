import { afterEach, describe, expect, it, vi } from "vitest";

import type { ThemeConfig } from "../src/protocol";
import { applyLauncherOffsets, applyTheme, isValidOffset, resolveScheme } from "../src/theme";

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

describe("isValidOffset (launcher offset injection hardening)", () => {
  it("accepts plain lengths and calc/min/max expressions", () => {
    for (const v of [
      "20px", "0", "1.5rem", "24px", "10%", "2em",
      "calc(100vw - 1180px)",
      "max(24px, calc((100vw - 1180px) / 2 + 24px))",
      "clamp(16px, 5vw, 48px)",
    ]) {
      expect(isValidOffset(v)).toBe(true);
    }
  });

  it("rejects values that could break out of the declaration", () => {
    for (const v of [
      "20px; position: absolute",   // ; — new declaration
      "20px} body{display:none",    // } — rule break
      "url(https://attacker/x)",    // url(
      "url(#a)",                    // url( without scheme
      'red"',                       // quote
      "20px/* c */",                // comment
      "expression(alert(1))",       // has ( but also… actually rejected by no forbidden char? see below
      "a".repeat(300),              // over the length cap
      "<script>",                   // angle brackets
      "20px @import x",             // @
      "20px\\0a",                   // backslash
    ]) {
      expect(isValidOffset(v)).toBe(false);
    }
  });
});

describe("applyLauncherOffsets", () => {
  it("sets the custom properties for valid values, skips undefined", () => {
    const host = document.createElement("div");
    applyLauncherOffsets(host, "24px", undefined);
    expect(host.style.getPropertyValue("--cb-offset-right")).toBe("24px");
    expect(host.style.getPropertyValue("--cb-offset-bottom")).toBe(""); // undefined → CSS default
  });

  it("ignores an invalid value (leaves the default)", () => {
    const host = document.createElement("div");
    applyLauncherOffsets(host, "20px;}evil{}", "40px");
    expect(host.style.getPropertyValue("--cb-offset-right")).toBe(""); // rejected
    expect(host.style.getPropertyValue("--cb-offset-bottom")).toBe("40px");
  });
});
