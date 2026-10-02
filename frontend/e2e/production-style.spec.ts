import { expect, test } from '@playwright/test'

test('生产构建保留高斯模糊且资源图标能够解码', async ({page}) => {
  // 使用固定背景隔离外部图片服务，直接验证构建后的浏览器计算样式。
  await page.route('https://api.yppp.net/**', route => route.fulfill({
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><path fill="#3588cc" d="M0 0h1280v720H0z"/></svg>',
  }))
  await page.goto('/#/i/testpilot/overview')
  await expect(page.locator('.instance-page-title h1')).toHaveText('testpilot')
  for (const selector of ['.sidebar', '.right-rail', '.panel']) {
    await expect(page.locator(selector).first()).toHaveCSS('backdrop-filter', 'blur(24px) saturate(1.3)')
  }
  // 二级贴片使用独立的较轻滤镜，资源卡不再沿用一级面的默认强度。
  await expect(page.locator('.resource-card').first()).toHaveCSS('backdrop-filter', 'blur(12px) saturate(1.2)')
  // 装饰玻璃层仍与一级面保持同一默认强度。
  await expect(page.locator('.glass-material').first()).toHaveCSS('backdrop-filter', 'blur(24px) saturate(1.3)')
  const icons = page.locator('.resource-icon-image')
  await expect(icons.first()).toBeVisible()
  await expect.poll(() => icons.evaluateAll(elements => elements.every(element =>
    element instanceof HTMLImageElement && element.complete && element.naturalWidth > 0,
  ))).toBe(true)
  // 无障碍模式仍应关闭模糊，防止调整前缀顺序破坏降级样式。
  await page.emulateMedia({forcedColors: 'active'})
  await expect(page.locator('.sidebar')).toHaveCSS('backdrop-filter', 'none')
  await expect(page.locator('.resource-card').first()).toHaveCSS('backdrop-filter', 'none')
})
