// Vitest global setup. Node 22.4+/26 ship an EXPERIMENTAL native `localStorage`
// global that throws without --localstorage-file; under vitest+jsdom it can shadow
// jsdom's real Storage on globalThis, breaking storage-dependent tests. When jsdom's
// window has a working Storage that differs from the global, re-bind the global to
// jsdom's (a real `Storage` instance, so `Storage.prototype` spies still work).
// No-op on Node versions without the native global (e.g. 24 LTS in CI + local dev).
for (const key of ["localStorage", "sessionStorage"] as const) {
  const fromJsdom = typeof window !== "undefined" ? window[key] : undefined;
  if (fromJsdom && (globalThis as Record<string, unknown>)[key] !== fromJsdom) {
    try {
      Object.defineProperty(globalThis, key, {
        value: fromJsdom,
        configurable: true,
        writable: true,
      });
    } catch {
      // native global is non-configurable — nothing more we can do here; CI pins an
      // unaffected Node LTS (see .github/workflows/ci.yml).
    }
  }
}
