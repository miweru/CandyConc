import { defineConfig, devices } from '@playwright/test'

const frontendPort = process.env.CANDYCONC_FRONTEND_PORT ?? '5173'
const frontendUrl = `http://127.0.0.1:${frontendPort}`
const isLiveBackendSmoke = process.env.CANDYCONC_LIVE_BACKEND_SMOKE === '1'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: !isLiveBackendSmoke,
  forbidOnly: !!process.env.CI,
  retries: isLiveBackendSmoke ? 0 : process.env.CI ? 2 : 0,
  workers: isLiveBackendSmoke || process.env.CI ? 1 : undefined,
  reporter: isLiveBackendSmoke ? 'line' : 'html',
  use: {
    baseURL: frontendUrl,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure'
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] }
    },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] }
    },
    {
      name: 'mobile-safari',
      use: { ...devices['iPhone 12'] }
    }
  ],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
    url: frontendUrl,
    reuseExistingServer: !process.env.CI,
    timeout: 120000
  }
})
