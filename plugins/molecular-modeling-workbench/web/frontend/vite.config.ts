import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Vite build config + vitest config share one entry point (T4.1).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/auth": "http://127.0.0.1:8765",
      "/runs": "http://127.0.0.1:8765",
      "/params": "http://127.0.0.1:8765",
      "/stream": "http://127.0.0.1:8765",
      "/analysis": "http://127.0.0.1:8765",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
