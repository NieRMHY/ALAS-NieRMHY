import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e', testMatch: '**/mock.spec.ts', workers: 1,
  use: {baseURL: 'http://127.0.0.1:5174', headless: true, locale: 'zh-CN', viewport: {width: 1440, height: 1100}},
  webServer: [
    {command: 'npm run mock', env: {AZURPILOT_MOCK_PORT: '22492'}, url: 'http://127.0.0.1:22492/healthz', reuseExistingServer: false},
    {command: 'npm run dev -- --mode mock --port 5174', env: {AZURPILOT_MOCK_PORT: '22492'}, url: 'http://127.0.0.1:5174', reuseExistingServer: false},
  ],
})
