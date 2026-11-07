import { defineConfig, devices } from "@playwright/test";

/**
 * Gate 1 end-to-end test. Starts its own API (port 8100, fresh versnq_e2e database, file
 * outbox) and production builds of both apps (3100 client, 3101 staff console), so it never
 * touches the dev servers or the demo data. Run with `make e2e`.
 */
export const E2E_STAFF_PASSWORD = "e2e-staff-password-1";
const backendEnv = { BACKEND_URL: "http://localhost:8100" };

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  workers: 1,
  reporter: [["list"]],
  use: { ...devices["Desktop Chrome"], trace: "retain-on-failure" },
  webServer: [
    {
      command: "../scripts/e2e-backend.sh",
      url: "http://localhost:8100/health",
      env: { E2E_STAFF_PASSWORD },
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run build && npx next start -p 3100",
      url: "http://localhost:3100/login",
      env: backendEnv,
      timeout: 300_000,
      reuseExistingServer: false,
    },
    {
      command: "cd ../frontend-admin && npm run build && npx next start -p 3101",
      url: "http://localhost:3101/login",
      env: backendEnv,
      timeout: 300_000,
      reuseExistingServer: false,
    },
  ],
});
