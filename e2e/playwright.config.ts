import { defineConfig, devices } from "@playwright/test";

// The stack under test is started outside Playwright (docker compose in CI, `make up` or the dev servers locally),
// so the same tests run against compose, a kind cluster or a deployed environment: set E2E_BASE_URL.
export default defineConfig({
  testDir: "./tests",
  timeout: 45_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,        // tests share one estate; review actions change it
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
