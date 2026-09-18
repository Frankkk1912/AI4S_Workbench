import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// RTL auto-cleanup relies on global afterEach; register it explicitly so the
// DOM is reset between tests without requiring vitest globals.
afterEach(() => {
  cleanup();
});
