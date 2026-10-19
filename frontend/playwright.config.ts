import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  // Modify by MHY, 心智用例使用独立 mock 配置，默认后端套件不重复执行。
  testIgnore: ['**/mock.spec.ts', '**/mind-*.spec.ts'],
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
