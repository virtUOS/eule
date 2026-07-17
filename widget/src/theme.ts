// Apply resolved theme tokens (docs/03) as CSS custom properties on the Shadow :host.
// dark_mode: auto → prefers-color-scheme; light/dark → forced.

import type { ThemeConfig } from "./protocol";

export type Scheme = "light" | "dark";

export function resolveScheme(mode: ThemeConfig["dark_mode"]): Scheme {
  if (mode === "light" || mode === "dark") return mode;
  const mql =
    typeof window !== "undefined" && window.matchMedia
      ? window.matchMedia("(prefers-color-scheme: dark)")
      : null;
  return mql && mql.matches ? "dark" : "light";
}

// Only genuine custom properties may be set. This stops a config/override from writing
// a real CSS property (e.g. `background: url(https://attacker/beacon)`) onto the host.
const TOKEN_KEY = /^--[a-zA-Z0-9-]+$/;

export function applyTheme(host: HTMLElement, theme: ThemeConfig, scheme: Scheme): void {
  const tokens = scheme === "dark" ? theme.dark : theme.light;
  for (const [key, value] of Object.entries({ ...tokens, ...(theme.radius ?? {}) })) {
    if (TOKEN_KEY.test(key)) host.style.setProperty(key, value);
  }
  host.style.setProperty("color-scheme", scheme);
}

// Launcher-mode offsets (host-configurable) are CSS <length> EXPRESSIONS — e.g.
// "max(24px, calc((100vw - 1180px) / 2 + 24px))" — set as the --cb-offset-* custom
// properties and substituted into the stylesheet via var(). setProperty already refuses
// an unparseable value, but we validate defensively in the same spirit as TOKEN_KEY:
// an allowlist of the characters a length/calc()/min()/max()/clamp()/var() expression
// needs, plus explicit bans on url(...) and comments. This rejects ';', '}', '<', '>',
// '@', quotes, backslash, ':' (so url()/data: can't appear), etc.
const OFFSET_VALUE = /^[a-zA-Z0-9 \t.,%()+*/-]{1,256}$/;

export function isValidOffset(value: string): boolean {
  return (
    OFFSET_VALUE.test(value) &&
    !value.includes("/*") &&
    !/url\(/i.test(value) &&
    !/expression\(/i.test(value)
  );
}

// Set the launcher offset custom properties from the (optional) host options. An
// omitted or rejected value leaves the CSS default (20px) in place — so a bad value
// degrades to today's rendering rather than breaking layout. Launcher mode only; the
// vars are unused by inline/standalone rules.
export function applyLauncherOffsets(
  host: HTMLElement,
  offsetRight?: string,
  offsetBottom?: string,
): void {
  for (const [prop, value] of [
    ["--cb-offset-right", offsetRight],
    ["--cb-offset-bottom", offsetBottom],
  ] as const) {
    if (value === undefined) continue;
    if (isValidOffset(value)) host.style.setProperty(prop, value);
    else console.warn(`[eule-widget] ignoring invalid ${prop} value: ${value}`);
  }
}

// Re-apply on OS scheme change when dark_mode is "auto". Returns an unsubscribe fn.
export function watchScheme(
  mode: ThemeConfig["dark_mode"],
  onChange: (scheme: Scheme) => void,
): () => void {
  if (mode !== "auto" || typeof window === "undefined" || !window.matchMedia) {
    return () => {};
  }
  const mql = window.matchMedia("(prefers-color-scheme: dark)");
  const handler = (): void => onChange(mql.matches ? "dark" : "light");
  mql.addEventListener("change", handler);
  return () => mql.removeEventListener("change", handler);
}
