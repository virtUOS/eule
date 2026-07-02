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

export function applyTheme(host: HTMLElement, theme: ThemeConfig, scheme: Scheme): void {
  const tokens = scheme === "dark" ? theme.dark : theme.light;
  for (const [key, value] of Object.entries(tokens)) {
    host.style.setProperty(key, value);
  }
  for (const [key, value] of Object.entries(theme.radius ?? {})) {
    host.style.setProperty(key, value);
  }
  host.style.setProperty("color-scheme", scheme);
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
