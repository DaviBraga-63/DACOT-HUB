const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    browserName: "chromium",
    headless: true,
    ignoreHTTPSErrors: true,
    screenshot: "only-on-failure",
    // Browser requests carry the ephemeral Pedidos bearer session. Keep failure
    // evidence to screenshots/report only so no token can land in an artifact.
    trace: "off",
    video: "off",
  },
});
