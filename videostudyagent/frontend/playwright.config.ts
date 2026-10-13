import { defineConfig } from "@playwright/test";
import path from "node:path";

process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.resolve(import.meta.dirname, "../.cache/ms-playwright");
const python = path.resolve(import.meta.dirname, "../backend", process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
export default defineConfig({
  testDir: "./e2e", workers: 1, timeout: 45000,
  outputDir: "../.cache/playwright-results", reporter: "list",
  use: { baseURL: "http://127.0.0.1:5174", trace: "retain-on-failure" },
  webServer: [
    { command: `"${python}" -m uvicorn tests.e2e_app:app --host 127.0.0.1 --port 8001`, cwd: "../backend", env: { VSA_E2E: "1" }, url: "http://127.0.0.1:8001/api/health", reuseExistingServer: false },
    { command: "npm run dev -- --port 5174", env: { VSA_API_PROXY: "http://127.0.0.1:8001" }, url: "http://127.0.0.1:5174", reuseExistingServer: false },
  ],
});
