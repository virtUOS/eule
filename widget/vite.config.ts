import { defineConfig } from "vite";
import { resolve } from "node:path";
import { devBackendStub } from "./dev-stub";

// Build to a single self-contained widget.js (IIFE) that embeds cleanly in any host.
export default defineConfig({
  // Dev-only stubbed gateway so `npm run dev` renders a working widget offline.
  plugins: [devBackendStub()],
  build: {
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
    include: ["tests/**/*.test.ts"],
  },
});
