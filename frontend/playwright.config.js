import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'html',
  timeout: 60000,
  // Global timeout for entire test run (10 minutes max)
  globalTimeout: 10 * 60 * 1000,

  use: {
    baseURL: process.env.BASE_URL || 'http://shizuha-nginx',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
    // Per-action timeout (10 seconds) - fails faster than test timeout
    actionTimeout: 10000,
    // Navigation timeout
    navigationTimeout: 30000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
