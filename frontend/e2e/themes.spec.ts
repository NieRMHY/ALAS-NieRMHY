import { expect, test, type Page } from '@playwright/test'

test.beforeEach(async ({page}) => {
  await page.route('https://www.clarity.ms/**', route => route.abort())
})

async function selectTheme(page: Page, name: string) {
  await page.getByRole('combobox', {name: '界面主题', exact: true}).click()
  await page.getByRole('option', {name, exact: true}).click()
}

async function selectMode(page: Page, name: string) {
  await page.getByRole('combobox', {name: '主题模式', exact: true}).click()
  await page.getByRole('option', {name, exact: true}).click()
}

async function expectFlat(page: Page) {
  const effects = await page.evaluate(() => [...document.querySelectorAll('body *')].flatMap(element => {
    if (!(element instanceof HTMLElement) || !element.getClientRects().length) return []
    return [null, '::before', '::after'].flatMap(pseudo => {
      const css = getComputedStyle(element, pseudo)
      if (pseudo && ['none', 'normal'].includes(css.content)) return []
      const issues = [css.backdropFilter, css.filter, css.backgroundImage, css.boxShadow, css.animationName].filter(value => value !== 'none')
      const alpha = css.backgroundColor.match(/(?:rgba\(.+, |\/\s*)([\d.]+)\)/)?.[1]
      if (alpha && Number(alpha) > 0 && Number(alpha) < 1) issues.push(css.backgroundColor)
      return issues.length ? [`${element.className}${pseudo ?? ''}: ${issues.join(', ')}`] : []
    })
  }))
  expect(effects).toEqual([])
}

test('简约首屏仅加载当前主题，五套配色即时生效并记忆', async ({page}, testInfo) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem('azurpilot.theme')) localStorage.setItem('azurpilot.theme', 'minimal')
  })
  const requests: string[] = []
  page.on('request', request => requests.push(request.url()))
  await page.goto('/#/interface')
  await expect(page.getByRole('group', {name: '配色方案'})).toBeVisible()
  await expect(page.getByRole('combobox', {name: '自定义背景'})).toHaveCount(0)
  expect(requests.some(url => /ClassicGlass|Wallpaper|\/classic-|\/theme\.css|api\.yppp/.test(url))).toBe(false)
  await expect(page.locator('.wallpaper, .glass-material, .glass-material-lens')).toHaveCount(0)
  await expect(page.locator('style[data-azurpilot-skin]')).toHaveCount(1)
  await expect(page.locator('.sidebar')).toHaveCSS('border-radius', '0px')
  await expect(page.locator('.topbar')).toHaveCSS('border-radius', '0px')
  await expect(page.locator('.panel').first()).toHaveCSS('border-radius', '14px')
  const colors = new Set<string>()
  for (const id of ['ocean', 'forest', 'violet', 'sand', 'slate']) {
    await page.locator(`input[name="palette"][value="${id}"]`).check()
    colors.add(await page.locator('html').evaluate(element => getComputedStyle(element).getPropertyValue('--accent').trim()))
    await expectFlat(page)
  }
  expect(colors.size).toBe(5)
  await page.reload()
  await expect(page.locator('input[name="palette"][value="slate"]')).toBeChecked()
  await page.screenshot({path: testInfo.outputPath('minimal-settings.png'), fullPage: true})
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({path: testInfo.outputPath('minimal-settings-mobile.png'), fullPage: true})
})

test('切换主题卸载旧材质，返回简约后不再发起装饰资源请求', async ({page}) => {
  await page.route('https://api.yppp.net/**', route => route.abort())
  await page.goto('/#/interface')
  await expect(page.locator('link[data-azurpilot-theme]')).toHaveCount(1)
  await expect(page.locator('.glass-material').first()).toBeVisible()
  await expect(page.getByRole('combobox', {name: '自定义背景'})).toBeVisible()
  await selectTheme(page, '简约')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'minimal')
  await expect(page.locator('link[data-azurpilot-theme], .glass-material, .wallpaper')).toHaveCount(0)
  await expect(page.getByRole('combobox', {name: '自定义背景'})).toHaveCount(0)
  await expectFlat(page)
  await selectTheme(page, '深色')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.locator('link[data-azurpilot-theme]')).toHaveCount(1)
  await expect(page.locator('.sidebar')).toHaveCSS('backdrop-filter', 'blur(24px) saturate(1.3)')
  await expect(page.getByRole('combobox', {name: '自定义背景'})).toBeVisible()
  await selectTheme(page, '简约')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'minimal')
  await expect(page.getByRole('combobox', {name: '自定义背景'})).toHaveCount(0)
  const requests: string[] = []
  page.on('request', request => requests.push(request.url()))
  await page.reload()
  await expect(page.locator('input[name="palette"][value="ocean"]')).toBeChecked()
  expect(requests.some(url => /ClassicGlass|Wallpaper|\/classic-|\/theme\.css|api\.yppp/.test(url))).toBe(false)
})

test('玻璃主题长页面滚动时两侧栏保持贴合视口', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'dark')
    localStorage.setItem('azurpilot.dev-mode', '1')
  })
  await page.goto('/#/i/testpilot/task/Alas')
  await expect(page.locator('.right-rail')).toBeVisible()

  await expect.poll(() => page.evaluate(() => { scrollTo(0, 500); return scrollY }), {timeout: 15000}).toBe(500)

  const sidebar = (await page.locator('.sidebar').boundingBox())!
  const rail = (await page.locator('.right-rail').boundingBox())!
  expect(Math.round(sidebar.y)).toBe(0)
  expect(Math.round(sidebar.height)).toBe(1100)
  expect(Math.round(rail.y + rail.height)).toBe(1100)
})

test('所有桌面主题的日志只在固定面板内部滚动', async ({page}) => {
  await page.route('https://api.yppp.net/**', route => route.abort())
  await page.setViewportSize({width: 1440, height: 900})
  await page.goto('/#/i/testpilot/overview')

  for (const theme of ['light', 'dark', 'minimal', 'extreme', 'legacy-light', 'legacy-dark']) {
    await page.evaluate(value => localStorage.setItem('azurpilot.theme', value), theme)
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const log = page.locator('.log-content')
    await expect(log).toBeVisible()
    await log.evaluate(element => {
      for (let index = 0; index < 300; index += 1) {
        const line = document.createElement('div')
        line.textContent = `日志高度回归 ${index}`
        element.appendChild(line)
      }
    })

    const layout = await page.evaluate(() => {
      const log = document.querySelector<HTMLElement>('.log-content')!
      const panel = document.querySelector<HTMLElement>('.monitor-panel')!
      return {
        pageHeight: document.documentElement.scrollHeight,
        viewportHeight: innerHeight,
        logClientHeight: log.clientHeight,
        logScrollHeight: log.scrollHeight,
        panelBottom: panel.getBoundingClientRect().bottom,
      }
    })
    expect(layout.pageHeight, theme).toBeLessThanOrEqual(layout.viewportHeight + 1)
    expect(layout.logScrollHeight, theme).toBeGreaterThan(layout.logClientHeight)
    expect(layout.panelBottom, theme).toBeLessThanOrEqual(layout.viewportHeight + 1)
  }
})

test('简约总览、弹窗、控件和移动端导航均使用实色', async ({page}, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'minimal')
    localStorage.setItem('azurpilot.dev-mode', '1')
  })
  await page.goto('/#/i/testpilot/overview')
  await expect(page.locator('.instance-page-title h1')).toHaveText('testpilot')
  await expectFlat(page)
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true)
  await page.setViewportSize({width: 1920, height: 1080})
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true)
  await page.setViewportSize({width: 1366, height: 768})
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true)
  await page.setViewportSize({width: 1440, height: 1100})
  await page.screenshot({path: testInfo.outputPath('minimal-overview.png'), fullPage: true})
  await page.getByRole('button', {name: '仪表盘设置', exact: true}).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expectFlat(page)
  await page.getByRole('button', {name: '关闭', exact: true}).click()
  await page.setViewportSize({width: 390, height: 844})
  await page.getByRole('button', {name: '打开导航', exact: true}).click()
  await expect(page.locator('.sidebar')).toHaveCSS('border-radius', '0px')
  await page.evaluate(() => {
    const left = document.querySelector('.sidebar-brand-left')!
    if (!left.querySelector('.sidebar-update-notice')) {
      const notice = document.createElement('a')
      notice.className = 'update-notice sidebar-update-notice'
      notice.href = '#/updater'
      notice.innerHTML = '<span>新</span>'
      left.appendChild(notice)
    }
  })
  const separation = await page.evaluate(() => {
    const closeBox = document.querySelector('.sidebar-brand .mobile-close')!.getBoundingClientRect()
    const noticeBox = document.querySelector('.sidebar-brand .sidebar-update-notice')!.getBoundingClientRect()
    return {
      closeLeft: closeBox.left,
      noticeRight: noticeBox.right,
      overlap: !(closeBox.right < noticeBox.left || closeBox.left > noticeBox.right || closeBox.bottom < noticeBox.top || closeBox.top > noticeBox.bottom),
    }
  })
  expect(separation.overlap).toBe(false)
  expect(separation.closeLeft).toBeGreaterThanOrEqual(separation.noticeRight)
  await page.screenshot({path: testInfo.outputPath('minimal-mobile-nav.png')})
  await page.getByRole('button', {name: '关闭导航', exact: true}).click()
  await page.getByRole('button', {name: '打开调度与任务', exact: true}).click()
  await expect(page.locator('.right-rail')).toBeInViewport()
  await expectFlat(page)
  await page.goto('/#/dev')
  await expect(page.getByRole('heading', {name: '表单控件', exact: true})).toBeVisible()
  await page.getByRole('combobox', {name: '下拉框', exact: true}).click()
  await expect(page.getByRole('listbox')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await page.keyboard.press('Escape')
  await page.getByRole('checkbox', {name: 'Alas', exact: true}).check()
  await expect(page.getByRole('checkbox', {name: 'Alas', exact: true})).toHaveCSS('background-color', 'rgb(36, 93, 190)')
  await expectFlat(page)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('主题下载未完成时的新选择不会被旧请求覆盖', async ({page}) => {
  await page.route('https://api.yppp.net/**', route => route.abort())
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  let requested = false
  await page.route('**/assets/minimal-*.js', async route => {
    requested = true
    await pending
    await route.continue()
  })
  await page.goto('/#/interface')
  await selectTheme(page, '简约')
  await expect.poll(() => requested).toBe(true)
  await selectTheme(page, '深色')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  const response = page.waitForResponse(response => /\/minimal-.*\.js/.test(response.url()))
  release()
  await response
  await expect(page.locator('style[data-azurpilot-skin]')).toHaveAttribute('data-azurpilot-skin', 'classic')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await page.evaluate(() => localStorage.getItem('azurpilot.theme'))).toBe('dark')
})

test('自动模式实时跟随系统，固定模式和配色预览正确切换', async ({page}, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.theme', 'minimal'))
  await page.emulateMedia({colorScheme: 'dark'})
  const requests: string[] = []
  page.on('request', request => requests.push(request.url()))
  await page.goto('/#/interface')
  await expect(page.getByRole('combobox', {name: '主题模式'})).toHaveText('自动')
  await expect(page.locator('html')).toHaveAttribute('data-color-mode', 'dark')
  await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark')
  const swatch = page.locator('.palette-option').filter({has: page.locator('input[name="palette"][value="ocean"]')}).locator('i').first()
  await expect(swatch).toHaveCSS('background-color', 'rgb(138, 180, 255)')
  const darkBackground = await page.locator('body').evaluate(element => getComputedStyle(element).backgroundColor)
  await expectFlat(page)
  await page.emulateMedia({colorScheme: 'light'})
  await expect(page.locator('html')).toHaveAttribute('data-color-mode', 'light')
  await expect(swatch).toHaveCSS('background-color', 'rgb(36, 93, 190)')
  await expect(page.locator('body')).not.toHaveCSS('background-color', darkBackground)
  await selectMode(page, '深色')
  await expect(page.locator('html')).toHaveAttribute('data-color-mode', 'dark')
  await page.emulateMedia({colorScheme: 'dark'})
  await page.emulateMedia({colorScheme: 'light'})
  await expect(page.locator('html')).toHaveAttribute('data-color-mode', 'dark')
  for (const id of ['ocean', 'forest', 'violet', 'sand', 'slate']) {
    await page.locator(`input[name="palette"][value="${id}"]`).check()
    await expectFlat(page)
  }
  await page.reload()
  await expect(page.getByRole('combobox', {name: '主题模式'})).toHaveText('深色')
  await expect(page.locator('html')).toHaveAttribute('data-color-mode', 'dark')
  await page.screenshot({path: testInfo.outputPath('minimal-dark-settings.png')})
  await selectMode(page, '浅色')
  await page.emulateMedia({colorScheme: 'dark'})
  await expect(page.locator('html')).toHaveAttribute('data-color-mode', 'light')
  expect(requests.some(url => /ClassicGlass|Wallpaper|\/classic-|\/theme\.css|api\.yppp/.test(url))).toBe(false)
  await page.route('https://api.yppp.net/**', route => route.abort())
  await selectTheme(page, '浅色')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  expect(await page.locator('html').evaluate(element => (element as HTMLElement).style.getPropertyValue('--accent'))).toBe('')
  await expect(page.locator('html')).not.toHaveAttribute('data-color-mode')
  await page.emulateMedia({colorScheme: 'light'})
  await page.emulateMedia({colorScheme: 'dark'})
  await expect(page.locator('html')).not.toHaveAttribute('data-color-mode')
})

test('自定义方案支持创建、校验、浅深通用配色、编辑和删除', async ({page}, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('azurpilot.theme', 'minimal'))
  await page.goto('/#/interface')
  await selectMode(page, '浅色')
  await page.getByRole('button', {name: '添加自定义配色'}).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByRole('textbox', {name: '主色', exact: true}).fill('#123')
  await expect(dialog.getByRole('button', {name: '保存并应用'})).toBeDisabled()
  await dialog.getByRole('textbox', {name: '主色', exact: true}).fill('#225599')
  await dialog.getByRole('textbox', {name: '副色', exact: true}).fill('#286747')
  await dialog.getByRole('button', {name: '保存并应用'}).click()
  const customRadio = page.locator('input[name="palette"][value^="custom:"]')
  await expect(customRadio).toBeChecked()
  await expect.poll(() => page.locator('html').evaluate(element => getComputedStyle(element).getPropertyValue('--accent'))).toBe('#225599')
  await page.reload()
  await expect(customRadio).toBeChecked()
  await selectMode(page, '深色')
  await expect(customRadio).toBeChecked()
  await page.getByRole('button', {name: '编辑方案'}).click()
  dialog = page.getByRole('dialog')
  await dialog.getByRole('textbox', {name: '主色', exact: true}).fill('#dd1122')
  await dialog.getByRole('button', {name: '取消', exact: true}).click()
  await expect(customRadio).toBeChecked()
  await page.getByRole('button', {name: '编辑方案'}).click()
  dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('textbox', {name: '主色', exact: true})).toHaveValue('#225599')
  await expect(dialog.getByRole('textbox', {name: '副色', exact: true})).toHaveValue('#286747')
  await page.setViewportSize({width: 390, height: 844})
  await expect(dialog).toBeInViewport()
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.screenshot({path: testInfo.outputPath('custom-palette-mobile.png')})
  await dialog.getByRole('textbox', {name: '主色', exact: true}).fill('#ddbbee')
  await dialog.getByRole('button', {name: '保存并应用'}).click()
  await expect(customRadio).toBeChecked()
  await expectFlat(page)
  await page.getByRole('button', {name: '删除方案'}).click()
  await expect(page.locator('input[name="palette"][value="ocean"]')).toBeChecked()
  await expect(customRadio).toHaveCount(0)
  await page.reload()
  await expect(customRadio).toHaveCount(0)
})

test('自定义背景支持 URL 与上传文件并在刷新后恢复', async ({page}) => {
  const remote = 'https://background.example/custom.jpg'
  await page.route(remote, route => route.fulfill({
    contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
  }))
  await page.route('https://api.yppp.net/**', route => route.abort())
  await page.goto('/#/interface')

  const source = page.getByRole('combobox', {name: '自定义背景'})
  await source.click()
  await page.getByRole('option', {name: '填写 URL'}).click()
  await page.getByRole('textbox', {name: '填写 URL'}).fill(remote)
  await page.getByRole('button', {name: '应用背景'}).click()
  await expect(page.locator('.wallpaper img')).toHaveAttribute('src', remote)
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('azurpilot.background') ?? '{}').source)).toBe('url')

  await source.click()
  await page.getByRole('option', {name: '上传文件'}).click()
  await page.locator('.background-upload input[type="file"]').setInputFiles({
    name: 'local.png',
    mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
  })
  await expect(page.locator('.background-upload')).toContainText('local.png')
  await expect(page.locator('.wallpaper img')).toHaveAttribute('src', /^blob:/)
  await page.reload()
  await expect(page.locator('.wallpaper img')).toHaveAttribute('src', /^blob:/)
  await expect(page.getByRole('combobox', {name: '自定义背景'})).toHaveText('上传文件')
})
test('紧凑主题收窄骨架与留白，且不叠加到其它主题', async ({page}) => {
  // addInitScript 每次导航都会重跑；无条件写入会在 reload 后覆盖掉用例中途设置的 extreme
  await page.addInitScript(() => {
    if (!localStorage.getItem('azurpilot.theme')) localStorage.setItem('azurpilot.theme', 'minimal')
  })
  await page.route('https://api.yppp.net/**', route => route.abort())
  await page.goto('/#/interface')

  const sidebar = page.locator('.sidebar')
  const content = page.locator('main').first()
  const label = page.locator('.field-label label').first()
  // 简约主题是标准密度
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'minimal')
  expect(Math.round((await sidebar.boundingBox())!.width)).toBe(232)
  // 内边距取左右方向：各主题的 main 顶部留白由内容自撑，左右才是主题差异所在
  expect(await content.evaluate(node => getComputedStyle(node).paddingLeft)).toBe('28px')
  const fontSize = await label.evaluate(node => getComputedStyle(node).fontSize)

  // 主题下拉里应能选到「紧凑」
  await page.getByRole('combobox', {name: '界面主题', exact: true}).click()
  await expect(page.getByRole('option', {name: '紧凑', exact: true})).toHaveCount(1)
  await page.keyboard.press('Escape')
  // 直接写入偏好并重载，避免下拉交互的时序影响后续布局断言
  await page.evaluate(() => localStorage.setItem('azurpilot.theme', 'extreme'))
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'extreme')
  expect(Math.round((await sidebar.boundingBox())!.width)).toBe(178)
  expect(await content.evaluate(node => getComputedStyle(node).paddingLeft)).toBe('4px')
  // 紧凑只改留白与骨架：字号保持契约值，避免整体缩放。
  expect(await label.evaluate(node => getComputedStyle(node).fontSize)).toBe(fontSize)
  expect(parseFloat(fontSize)).toBeGreaterThanOrEqual(14)
  expect(await page.locator('html').evaluate(node => getComputedStyle(node).zoom || '1')).toBe('1')
  await expectFlat(page)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

  // 刷新后主题仍保持
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'extreme')
  expect(Math.round((await sidebar.boundingBox())!.width)).toBe(178)

  // 总览页：与面包屑重复的标题行整行省略，实例设置按钮移入日志面板工具栏
  await page.goto('/#/i/testpilot/overview')
  await expect(page.locator('.instance-page-title')).toHaveCount(0)
  const settingsButton = page.locator('.monitor-tabs .button')
  await expect(settingsButton).toHaveCount(1)
  await expect(settingsButton).toContainText('资源卡片设置')
  // 窄屏（≤950px）下 .app-shell 变 block，顶栏不应再叠加右栏宽度撑出横向滚动
  await page.setViewportSize({width: 900, height: 700})
  await page.waitForTimeout(300)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.setViewportSize({width: 1440, height: 1100})
  await page.waitForTimeout(300)
  await page.goto('/#/interface')

  // 切回简约与深色都应回到标准密度，证明紧凑已成为独立主题而非叠加项
  await selectTheme(page, '简约')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'minimal')
  expect(Math.round((await sidebar.boundingBox())!.width)).toBe(232)
  expect(await content.evaluate(node => getComputedStyle(node).paddingLeft)).toBe('28px')

  await selectTheme(page, '深色')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(Math.round((await sidebar.boundingBox())!.width)).toBe(232)
  // 经典主题的 main 左右内边距是 32px，与简约的 28px 不同
  expect(await content.evaluate(node => getComputedStyle(node).paddingLeft)).toBe('32px')
})

test('紧凑主题可把调度与计划栏换到内容区左侧，切回其它主题即复位', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'extreme')
    localStorage.setItem('azurpilot.dev-mode', '1')
  })
  await page.route('https://api.yppp.net/**', route => route.abort())
  const order = () => page.locator('.app-shell').evaluate(node => [...node.children].map(child => child.className.split(' ')[0]))
  const rail = page.locator('.right-rail')
  const main = page.locator('main').first()

  await page.goto('/#/i/testpilot/overview')
  await expect(rail).toBeVisible()
  expect(await order()).toEqual(['skip-link', 'sidebar', 'main-shell', 'right-rail'])
  const defaultRailX = (await rail.boundingBox())!.x
  expect(defaultRailX).toBeGreaterThan((await main.boundingBox())!.x)

  // 换位在界面设置里切换；列序走 DOM，Tab 顺序才会跟着视觉走
  await page.goto('/#/interface')
  await page.getByText('计划栏在左').click()
  await page.goto('/#/i/testpilot/overview')
  await expect(rail).toBeVisible()
  expect(await order()).toEqual(['skip-link', 'sidebar', 'right-rail', 'main-shell'])
  expect((await rail.boundingBox())!.x).toBeLessThan((await main.boundingBox())!.x)
  // 顶栏改为向左跨过右栏，仍不产生横向滚动
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  expect(await rail.evaluate(node => getComputedStyle(node).borderRightWidth)).toBe('1px')

  // 宽度档位写进内联变量，切换主题时必须清掉，否则简约会跟着用紧凑的栏宽
  await page.goto('/#/interface')
  await page.getByRole('combobox', {name: '计划栏宽度'}).click()
  await page.getByRole('option', {name: '更宽（360px）'}).click()
  await page.goto('/#/i/testpilot/overview')
  expect(Math.round((await rail.boundingBox())!.width)).toBe(360)

  await page.goto('/#/interface')
  await selectTheme(page, '简约')
  await page.goto('/#/i/testpilot/overview')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'minimal')
  expect(await order()).toEqual(['skip-link', 'sidebar', 'main-shell', 'right-rail'])
  expect(await page.locator('html').evaluate(node => node.style.getPropertyValue('--right-rail-width'))).toBe('')
})

test('紧凑主题改用浮层滚动条：原生条不再占位，移进去才显形，切走主题即还原', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'extreme')
    localStorage.setItem('azurpilot.dev-mode', '1')
  })
  await page.route('https://api.yppp.net/**', route => route.abort())
  await page.goto('/#/i/testpilot/overview')
  await expect(page.locator('.rail-task-list')).toBeVisible()

  // 浮层轨道已挂上但默认不显示
  const rail = page.locator('.overlay-scrollbar')
  await expect(rail).toHaveCount(1)
  await expect(rail).not.toHaveAttribute('data-visible', 'on')

  // 内容长到溢出后，运行时扫描要把容器标记出来、把原生条压成 0 宽（等于不占内容宽度）；
  // 这一步不依赖鼠标移入 —— 否则异步加载完的列表会先画出常驻原生条
  await page.locator('.log-content').evaluate(element => {
    for (let index = 0; index < 200; index += 1) element.appendChild(document.createElement('div')).textContent = `填充日志 ${index}`
  })
  await expect.poll(() => page.locator('.log-content').evaluate(node => getComputedStyle(node).scrollbarWidth)).toBe('none')

  // 把鼠标移进去才显形，且是直角
  await page.locator('.log-content').hover()
  await expect(rail).toHaveAttribute('data-visible', 'on')
  expect(await page.locator('.overlay-scrollbar-thumb').evaluate(node => getComputedStyle(node).borderRadius)).toBe('0px')
  // 轨道右缘贴住滚动容器的右边界，不侵占内容
  const edges = await page.evaluate(() => ({
    rail: document.querySelector('.overlay-scrollbar')!.getBoundingClientRect(),
    box: document.querySelector('.log-content')!.getBoundingClientRect(),
  }))
  expect(Math.round(edges.rail.right)).toBe(Math.round(edges.box.right))

  // 切回简约：轨道移除，原生滚动条声明还原
  await page.goto('/#/interface')
  await selectTheme(page, '简约')
  await page.goto('/#/i/testpilot/overview')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'minimal')
  await expect(page.locator('.overlay-scrollbar')).toHaveCount(0)
  expect(await page.locator('.log-content').evaluate(node => getComputedStyle(node).scrollbarWidth)).not.toBe('none')
})
