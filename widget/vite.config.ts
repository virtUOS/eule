import { defineConfig } from "vitest/config";
import { resolve } from "node:path";
import { devBackendStub } from "./dev-stub";

// Build to a single self-contained widget.js (IIFE) that embeds cleanly in any host.
export default defineConfig({
  // Dev-only stubbed gateway so `npm run dev` renders a working widget offline.
  plugins: [devBackendStub()],
  build: {
    // PINNED browser floor — do not let a Vite major move it silently. The widget's
    // runtime APIs already require Safari 14.1+ (fetch body streaming for SSE), so
    // this is the NEWEST syntax target that doesn't exceed the API floor. It equals
    // Vite 5's old 'modules' default, i.e. the floor we have always shipped.
    target: ["es2020", "edge88", "firefox78", "chrome87", "safari14"],
    lib: {
      entry: resolve(__dirname, "src/index.ts"),
      name: "WolkeWidget",
      fileName: () => "widget.js",
      formats: ["iife"],
    },
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["tests/setup.ts"],
    include: ["tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      // Vitest owns the pure-logic modules. The DOM-orchestration layer
      // (widget.ts, dom.ts, render.ts, index.ts) and static assets (icons/i18n/styles)
      // are covered by the Playwright e2e suite (T10-A/B + review-fix specs), so
      // including them here would report a misleading unit-coverage number.
      include: ["src/sse.ts", "src/a11y.ts", "src/theme.ts", "src/persist.ts"],
      reporter: ["text", "text-summary"],
    },
  },
});
