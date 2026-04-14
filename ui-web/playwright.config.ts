import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: process.env.UI_WEB_BASE_URL ?? "http://localhost:3000",
    headless: true,
  },
});
