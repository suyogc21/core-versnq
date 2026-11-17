import { defineConfig, devices } from "@playwright/test";

/** The green-tick walk-through (docs/walkthrough.md) against the LIVE server, in the throwaway
 * test company only. Never part of `make e2e`: run it by hand with the test company's sign-in
 * in the environment (WT_SLUG, WT_EMAIL, WT_PASSWORD, WT_TOTP). */
export default defineConfig({
  testDir: ".",
  timeout: 300_000,
  workers: 1,
  reporter: [["list"]],
  use: { ...devices["Desktop Chrome"], trace: "retain-on-failure" },
});
