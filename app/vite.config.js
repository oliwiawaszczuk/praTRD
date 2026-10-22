import { defineConfig } from "vitest/config";
import { sveltekit } from "@sveltejs/kit/vite";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
import adapter from "@sveltejs/adapter-static";

const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [
    // SvelteKit 3: config lives here (svelte.config.js is no longer read).
    // Tauri has no Node server → static adapter with SPA fallback, SSR off in +layout.ts.
    sveltekit({
      preprocess: vitePreprocess(),
      adapter: adapter({ fallback: "index.html" }),
    }),
  ],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || "127.0.0.1",
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  build: {
    // WebView2 / WKWebView / WebKitGTK (Ubuntu 22.04) all support ES2022.
    target: "es2022",
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
});
