import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  // 股票规格依赖外部交易所 mock 服务，由 playwright.stock.config.ts 启动。
  testIgnore: ['**/mock.spec.ts', '**/stock-exchange/**'],
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60000,
  use: {baseURL: 'http://127.0.0.1:22391', headless: true, locale: 'zh-CN', viewport: {width: 1440, height: 1100}},
  webServer: {
    command: 'uv run python -m tests.serve_frontend',
    cwd: '..',
    url: 'http://127.0.0.1:22391/healthz',
    reuseExistingServer: !process.env.CI,
    timeout: 60000,
  },
})
