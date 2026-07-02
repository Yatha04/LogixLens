import { defineConfig } from "vitest/config";

// Integration tests: exercise the real FastAPI backend over HTTP.
// Requires the backend running in mock mode on :8000 (see README).
export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    include: ["src/**/*.integration.test.ts"],
    testTimeout: 30_000,
  },
});
