import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: process.env.VSA_API_PROXY || "http://127.0.0.1:8000" } },
  },
  preview: { host: "127.0.0.1" },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/tests/setup.ts"],
    clearMocks: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
