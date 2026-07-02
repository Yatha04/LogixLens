import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev proxy: REST + WebSocket both go to the FastAPI backend on :8000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    // jsdom so component smoke tests (@testing-library/react) run; pure-logic
    // tests run fine under it too.
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Integration tests hit a live backend and run under a separate config.
    exclude: ["**/node_modules/**", "src/**/*.integration.test.ts"],
  },
});
