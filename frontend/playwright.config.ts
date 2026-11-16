import { defineConfig, devices } from '@playwright/test'

const webkitProjects = process.env.PLAYWRIGHT_WEBKIT === '1' ? [{
  name: 'webkit-mobile-safari',
  testMatch: '**/mobile-safari.spec.ts',
  use: {
    ...devices['iPhone 17'],
    launchOptions: process.env.PLAYWRIGHT_WEBKIT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_WEBKIT_EXECUTABLE_PATH }
      : undefined,
  },
}] : []

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  projects: [{
    name: 'chromium',
    testIgnore: '**/mobile-safari.spec.ts',
    use: {
      ...devices['Desktop Chrome'],
      launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
        ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
        : undefined,
    },
  }, ...webkitProjects],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5173/connect',
    reuseExistingServer: true,
    timeout: 30_000,
  },
})
