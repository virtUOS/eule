import { describe, expect, it } from "vitest";

import type { ThemeConfig } from "../src/protocol";
import { applyTheme } from "../src/theme";

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
