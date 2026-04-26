import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/web',
  testMatch: '**/*.e2e.ts',
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:5299',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['desktop chrome'] },
    },
  ],

  webServer: {
    command: 'npm run dev --prefix spiral-ui',
    url: 'http://localhost:5299',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
