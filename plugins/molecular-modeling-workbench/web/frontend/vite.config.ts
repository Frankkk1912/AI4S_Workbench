import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Vite build config + vitest config share one entry point (T4.1).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
