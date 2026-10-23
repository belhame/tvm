import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '.', testMatch: '**/*.spec.js', timeout: 90000,
  fullyParallel: false, workers: 1, retries: 0,
  reporter: [['list']], outputDir: '../../.local/browser-results',
  use: {
    actionTimeout: 10000,
    baseURL: process.env.TVM_E2E_URL || 'http://127.0.0.1:8001',
    headless: true, viewport: { width: 1440, height: 1000 },
    launchOptions: { executablePath: process.env.TVM_CHROMIUM_PATH || undefined, args: ['--no-sandbox', '--disable-dev-shm-usage'] },
    screenshot: 'only-on-failure', trace: 'off',
  },
});
