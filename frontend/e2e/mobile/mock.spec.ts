import { expect, test, type Page } from '@playwright/test'

test.use({viewport: {width: 375, height: 812}, isMobile: true, hasTouch: true})

test.beforeEach(async ({page}) => {
  await page.route('https://**/*', route => route.abort())
})

async function preferences(page: Page, theme: string, material = 'glass') {
  await page.addInitScript(({theme, material}) => {
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.theme', theme)
    localStorage.setItem('azurpilot.material', material)
    localStorage.removeItem('azurpilot.last-path')
  }, {theme, material})
}

async function expectContentBelowTopbar(page: Page) {
  const topbar = (await page.locator('.topbar').boundingBox())!
  const main = (await page.locator('main').boundingBox())!
  expect(main.y).toBeCloseTo(topbar.y + topbar.height, 0)
  expect(main.height).toBeGreaterThan(200)
  expect(main.y + main.height).toBeLessThanOrEqual(page.viewportSize()!.height + 1)
  await expect(page.locator('.nav-handle')).toBeHidden()
}

async function expectNoPageOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await page.locator('main').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
}

for (const theme of ['light', 'dark']) {
  for (const material of ['glass', 'plain']) {
    test(`移动端新版 ${theme} ${material} 正文可见，抽屉不占位且断点切换正常`, async ({page}, testInfo) => {
      await preferences(page, theme, material)
      const errors: string[] = []
      page.on('pageerror', error => errors.push(error.message))
      await page.goto('/#/i/demo-main/overview')
      const title = page.locator('.instance-page-title h1')
      await expect(title).toHaveText('demo-main')
      await expect(title).toBeInViewport()
      await expectContentBelowTopbar(page)

      const mainBefore = await page.locator('main').boundingBox()
      const rail = page.locator('.right-rail')
      await expect(rail).toBeHidden()
      await expect(rail).toHaveCSS('position', 'fixed')
      await page.getByRole('button', {name: '打开调度与任务', exact: true}).click()
      await expect(rail).toBeInViewport()
      await expect(rail.getByRole('button', {name: '启动调度器', exact: true})).toBeInViewport()
      expect(await page.locator('main').boundingBox()).toEqual(mainBefore)
      await rail.getByRole('button', {name: '关闭调度与任务', exact: true}).click()
      await expect(rail).toBeHidden()

      await page.getByRole('button', {name: '打开导航', exact: true}).click()
      await expect(page.locator('.sidebar')).toBeInViewport()
      await page.getByRole('button', {name: '关闭导航', exact: true}).click()
      await expect(title).toBeInViewport()
      const tabs = (await page.locator('.monitor-tabs').boundingBox())!
      const tools = (await page.locator('.monitor-panel .log-toolbar').boundingBox())!
      expect(tools.y).toBeGreaterThanOrEqual(tabs.y + tabs.height)
      await page.screenshot({path: testInfo.outputPath('overview-mobile.png'), animations: 'disabled'})

      await page.goto('/#/i/demo-main/task/Alas')
      const fields = page.locator('.field-row')
      await expect(fields.first()).toBeInViewport()
      await expectContentBelowTopbar(page)
      await fields.last().scrollIntoViewIfNeeded()
      await expect(fields.last()).toBeInViewport()
      await expect(page.locator('.topbar')).toBeInViewport()

      // 横屏与断点两侧都检查正文，防止桌面网格规则重新泄漏到抽屉布局。
      await page.goto('/#/i/demo-main/overview')
      for (const viewport of [{width: 320, height: 640}, {width: 812, height: 375}, {width: 950, height: 844}]) {
        await page.setViewportSize(viewport)
        await expect(title).toBeInViewport()
        await expectContentBelowTopbar(page)
        await expect(rail).toHaveCSS('position', 'fixed')
        await expectNoPageOverflow(page)
      }
      for (const width of [951, 1280]) {
        await page.setViewportSize({width, height: 900})
        await expect(rail).toHaveCSS('position', 'relative')
        await expect(rail).toBeInViewport()
        await expect(title).toBeInViewport()
      }
      await page.screenshot({path: testInfo.outputPath('overview-desktop.png'), animations: 'disabled'})
      await page.setViewportSize({width: 390, height: 844})
      await expect(rail).toHaveCSS('position', 'fixed')
      await expect(rail).toBeHidden()
      await expectContentBelowTopbar(page)
      expect(errors).toEqual([])
    })
  }

  test(`移动端新版 ${theme} 首页单列排列且可滚动到最后一个实例`, async ({page}, testInfo) => {
    await preferences(page, theme)
    await page.goto('/')
    const cards = page.locator('.home-instance-grid .instance-card')
    await expect(cards).toHaveCount(4)
    const deck = (await page.locator('.home-deck').boundingBox())!
    const main = (await page.locator('.home-main').boundingBox())!
    expect(main.x).toBeCloseTo(deck.x, 0)
    expect(main.width).toBeCloseTo(deck.width, 0)
    expect(main.y).toBeGreaterThanOrEqual(deck.y + deck.height - 1)
    await expect(page.locator('.nav-handle')).toBeHidden()
    await page.screenshot({path: testInfo.outputPath('home-mobile.png'), animations: 'disabled'})
    for (const viewport of [{width: 375, height: 812}, {width: 812, height: 375}]) {
      await page.setViewportSize(viewport)
      await cards.last().scrollIntoViewIfNeeded()
      await expect(cards.last()).toBeInViewport()
      expect(await page.locator('.home-editorial').evaluate(element => element.scrollTop)).toBeGreaterThan(0)
      await expect(page.locator('.topbar')).toBeInViewport()
      expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1)).toBe(true)
    }
  })
}

for (const theme of ['light', 'dark', 'minimal', 'extreme', 'legacy-light', 'legacy-dark']) {
  test(`移动端 ${theme} 统计分类完整显示，搜索与导出可用`, async ({page}, testInfo) => {
    await preferences(page, theme)
    await page.goto('/#/i/demo-main/statistics')
    const categories = page.locator('.statistics-category-control')
    const select = page.getByRole('combobox', {name: '统计分类', exact: true})
    await expect(select).toBeInViewport()
    await expect(categories).toBeHidden()
    const search = page.locator('.statistics-table .table-search').first()
    const heading = page.locator('.statistics-table .panel-heading').first()
    await expect(search).toBeVisible()
    const title = (await heading.locator('h3').boundingBox())!
    const input = (await search.locator('input').boundingBox())!
    const exportButton = (await heading.getByRole('button', {name: '导出明细', exact: true}).boundingBox())!
    expect(input.y).toBeGreaterThanOrEqual(title.y + title.height)
    expect(exportButton.width).toBeGreaterThan(40)
    await expectNoPageOverflow(page)

    await page.getByRole('button', {name: '样式编辑', exact: true}).click()
    const merge = page.locator('.statistics-category-picker .statistics-single-view')
    await expect(merge).toBeVisible()
    await expectNoPageOverflow(page)
    await page.locator('.statistics-category-picker').screenshot({path: testInfo.outputPath('statistics-category-edit.png'), animations: 'disabled'})
    await page.getByRole('button', {name: '样式编辑', exact: true}).click()

    for (const width of [320, 375, 390, 950]) {
      await page.setViewportSize({width, height: 844})
      await select.scrollIntoViewIfNeeded()
      await expect(select).toBeInViewport({ratio: 1})
      const box = (await select.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      expect(await select.locator('span').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
      await expectNoPageOverflow(page)
    }
    await page.setViewportSize({width: 375, height: 812})
    await select.scrollIntoViewIfNeeded()
    await page.screenshot({path: testInfo.outputPath('statistics-mobile.png'), animations: 'disabled'})
    await page.locator('.statistics-category-picker').screenshot({path: testInfo.outputPath('statistics-category-picker.png'), animations: 'disabled'})
    const labels = await page.locator('.statistics-category-select select option').allTextContents()
    for (const label of labels) {
      await select.click()
      const option = page.getByRole('option', {name: label, exact: true})
      await option.scrollIntoViewIfNeeded()
      await expect(option).toBeInViewport({ratio: 1})
      expect(await option.locator('span').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
      await option.click()
      await expect(select).toHaveText(label)
    }
    await expectNoPageOverflow(page)
    await select.click()
    await page.getByRole('listbox').evaluate(element => {element.scrollTop = 0})
    await page.getByRole('listbox').screenshot({path: testInfo.outputPath('statistics-category-menu.png'), animations: 'disabled'})
    await page.keyboard.press('Escape')
    if (theme !== 'extreme') {
      await page.setViewportSize({width: 1920, height: 1080})
      await expect(categories).toBeVisible()
      await expect(select).toBeHidden()
      await categories.screenshot({path: testInfo.outputPath('statistics-category-desktop.png'), animations: 'disabled'})
    }
  })
}
