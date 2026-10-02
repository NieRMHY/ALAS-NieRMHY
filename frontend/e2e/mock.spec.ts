import { expect, test } from '@playwright/test'

test('PR1096 模拟预览焦点、区域键盘与窄屏布局回归', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'glass')
    localStorage.setItem('azurpilot.language', 'zh-CN')
    localStorage.setItem('azurpilot.background', JSON.stringify({source: 'off'}))
  })
  await page.goto('/#/interface')
  const opener = page.getByRole('button', {name: '预览假实例页', exact: true})
  await opener.click()
  const preview = page.getByRole('dialog', {name: '预览假实例页', exact: true})
  await expect(preview).toHaveAttribute('aria-modal', 'true')
  const first = preview.locator('a[href]').first()
  await expect(first).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  const last = preview.locator('.inspector-footer button')
  await expect(last).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(first).toBeFocused()
  const tabs = preview.getByRole('tab')
  await tabs.first().focus()
  await page.keyboard.press('ArrowRight')
  await expect(tabs.nth(1)).toBeFocused()
  await expect(tabs.nth(1)).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('End')
  await expect(tabs.last()).toBeFocused()
  await page.keyboard.press('Home')
  await expect(tabs.first()).toBeFocused()
  for (const width of [375, 420]) {
    await page.setViewportSize({width, height: 800})
    await expect(preview.locator('.mock-preview-shell')).toHaveCSS('width', `${width}px`)
  }
  await page.screenshot({path: 'test-results/pr1096-preview-narrow.png'})
  await page.setViewportSize({width: 1440, height: 1100})
  await last.click()
  await expect(preview).toHaveCount(0)
  await expect(opener).toBeFocused()
})

test('画布框选、快捷键、中键平移与同色连接规则', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {localStorage.setItem('azurpilot.theme','light'); localStorage.setItem('azurpilot.language','zh-CN')})
  await page.goto('/#/i/demo-alt/task/SchedulerProgram')
  await expect(page.locator('.program-editor')).toBeVisible()
  const doc = {schemaVersion:1,name:'快捷键与类型验收',entry:'start',subgraphs:[],variables:[],viewport:{x:0,y:0,zoom:1}, nodes:[
    {id:'start',type:'entry',label:'',params:{},position:{x:0,y:0}},
    {id:'bool',type:'logic',label:'',params:{operator:'and',a:true,b:true},position:{x:0,y:300}},
    {id:'math',type:'math',label:'',params:{operator:'+',a:10,b:20},position:{x:320,y:300}},
    {id:'wait',type:'wait',label:'',params:{seconds:60},position:{x:640,y:300}},
  ],edges:[{id:'next',source:'start',sourcePort:'next',target:'wait',targetPort:'in',kind:'control'}]}
  await page.locator('.program-file input').setInputFiles({name:'keyboard.scheduler.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(doc))})
  await expect(page.locator('.react-flow__node')).toHaveCount(4)
  await page.getByRole('button',{name:'展开画布',exact:true}).click()
  await page.locator('.program-canvas').scrollIntoViewIfNeeded()
  await page.locator('.react-flow__controls-fitview').click()
  const bool = page.locator('.react-flow__node[data-id="bool"]'), math = page.locator('.react-flow__node[data-id="math"]'), wait = page.locator('.react-flow__node[data-id="wait"]')
  await page.waitForTimeout(150); const a = (await bool.boundingBox())!, b = (await math.boundingBox())!
  await page.mouse.move(a.x - 8,a.y + 4)
  await page.mouse.down()
  await page.mouse.move(b.x + b.width + 8,Math.max(a.y+a.height,b.y+b.height)+8,{steps:12})
  await page.mouse.up()
  await expect(page.locator('.react-flow__node.selected')).toHaveCount(2)
  await page.keyboard.press('Control+c')
  await page.keyboard.press('Control+v')
  await expect(page.locator('.react-flow__node')).toHaveCount(6)
  await expect(page.locator('.react-flow__node.selected')).toHaveCount(2)
  await page.keyboard.press('Backspace')
  await expect(page.locator('.react-flow__node')).toHaveCount(4)
  await page.keyboard.press('Control+z')
  await expect(page.locator('.react-flow__node')).toHaveCount(6)
  await page.keyboard.press('Control+Shift+z')
  await expect(page.locator('.react-flow__node')).toHaveCount(4)
  await math.locator('.program-card-heading').click()
  await page.keyboard.press('Control+x')
  await expect(page.locator('.react-flow__node')).toHaveCount(3)
  await page.keyboard.press('Control+z')
  await expect(page.locator('.react-flow__node')).toHaveCount(4)
  const numberInput = math.locator('.program-card-settings').getByLabel('输入 A',{exact:true})
  await numberInput.fill('123')
  await numberInput.press('End')
  await numberInput.press('Backspace')
  await expect(numberInput).toHaveValue('12')
  await expect(page.locator('.react-flow__node')).toHaveCount(4)
  const beforePan = (await bool.boundingBox())!
  const canvas = (await page.locator('.program-canvas').boundingBox())!
  await page.mouse.move(canvas.x + canvas.width / 2,canvas.y + 50)
  await page.mouse.down({button:'middle'})
  await page.mouse.move(canvas.x + canvas.width / 2 + 45,canvas.y + 75,{steps:8})
  await page.mouse.up({button:'middle'})
  expect((await bool.boundingBox())!.x).toBeCloseTo(beforePan.x + 45,0)
  expect((await bool.boundingBox())!.y).toBeCloseTo(beforePan.y + 25,0)
  const source = math.locator('[data-handleid="data:value"]'), target = wait.locator('[data-handleid="data:seconds"]')
  expect(await source.evaluate(node => getComputedStyle(node).backgroundColor)).toBe(await target.evaluate(node => getComputedStyle(node).backgroundColor))
  await source.dragTo(target)
  await expect(page.locator('.program-data-edge')).toHaveCount(1)
  const booleanOutput = bool.locator('[data-handleid="data:value"]')
  expect(await booleanOutput.evaluate(node => getComputedStyle(node).backgroundColor)).not.toBe(await target.evaluate(node => getComputedStyle(node).backgroundColor))
  await booleanOutput.dragTo(target)
  await expect(page.locator('.program-data-edge')).toHaveCount(1)
  await page.screenshot({path:'test-results/scheduler-editor-shortcuts.png',fullPage:true,animations:'disabled'})
  expect(errors).toEqual([])
})

test('资源和任务在卡片内直接选择，表单不触发拖拽，保存和模拟使用新参数', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {localStorage.setItem('azurpilot.theme', 'light'); localStorage.setItem('azurpilot.language', 'zh-CN')})
  await page.goto('/#/i/demo-error/task/SchedulerProgram')
  await page.getByRole('button', {name:'载入原调度方案',exact:true}).click()
  await page.locator('.program-library').getByRole('button', {name:'读取资源',exact:true}).click()
  const resource = page.locator('.react-flow__node').filter({has:page.locator('.program-card-heading strong').filter({hasText:/^读取资源$/})})
  const inline = resource.locator('.program-card-settings')
  await expect(inline.getByLabel('读取资源',{exact:true})).toBeVisible()
  const initialPosition = await resource.getAttribute('style')
  await inline.getByLabel('读取资源',{exact:true}).selectOption('ActionPoint')
  await inline.getByLabel('读取数值',{exact:true}).selectOption('total')
  await inline.getByLabel('有效期（秒）',{exact:true}).fill('120')
  await inline.getByLabel('过期时自动刷新',{exact:true}).uncheck()
  expect(await resource.getAttribute('style')).toBe(initialPosition)
  await expect(page.locator('.program-properties').getByLabel('有效期（秒）',{exact:true})).toHaveValue('120')
  await page.locator('.program-library').getByRole('button', {name:'读取指定任务',exact:true}).click()
  const task = page.locator('.react-flow__node').filter({has:page.locator('.program-card-heading strong').filter({hasText:/^读取指定任务$/})})
  await task.locator('.program-card-settings').getByLabel('指定任务',{exact:true}).selectOption('Research')
  await page.locator('.program-connect summary').click()
  const taskId = (await task.getAttribute('data-id'))!
  await page.getByLabel('来源卡片',{exact:true}).selectOption(taskId)
  await page.getByLabel('输出端口',{exact:true}).selectOption('data:value')
  await page.getByLabel('目标卡片',{exact:true}).selectOption('run')
  await page.getByLabel('输入端口',{exact:true}).selectOption('data:task')
  await page.getByRole('button', {name:'连接',exact:true}).click()
  await expect(page.locator('.react-flow__node[data-id="run"]').getByLabel('执行任务',{exact:true})).toBeDisabled()
  await page.getByRole('button', {name:'调试',exact:true}).click()
  await page.getByRole('button', {name:'模拟运行',exact:true}).click()
  await expect(page.locator('.program-trace')).toContainText('Research')
  // 验证调试面板环境资源展开与滚轮/滚动条交互顺畅且不被画布劫持
  const consoleBody = page.locator('.program-console-body')
  await page.locator('.program-sim-params summary').click()
  await expect(page.getByLabel('含体力箱的总行动力', {exact:true})).toBeVisible()
  const scrollable = await consoleBody.evaluate(el => el.scrollHeight > el.clientHeight)
  expect(scrollable).toBe(true)
  const bodyBox = (await consoleBody.boundingBox())!
  await page.mouse.move(bodyBox.x + bodyBox.width / 2, bodyBox.y + bodyBox.height / 2)
  await page.mouse.wheel(0, 300)
  await page.waitForTimeout(100)
  const scrolledTop = await consoleBody.evaluate(el => el.scrollTop)
  expect(scrolledTop).toBeGreaterThan(0)
  await page.getByRole('button', {name:'保存草稿',exact:true}).click()
  await page.reload()
  await expect(inline.getByLabel('读取资源',{exact:true})).toHaveValue('ActionPoint')
  await expect(inline.getByLabel('读取数值',{exact:true})).toHaveValue('total')
  await expect(inline.getByLabel('有效期（秒）',{exact:true})).toHaveValue('120')
  await expect(inline.getByLabel('过期时自动刷新',{exact:true})).not.toBeChecked()
  await expect(task.locator('.program-card-settings').getByLabel('指定任务',{exact:true})).toHaveValue('Research')
  await page.getByRole('button', {name:'展开画布',exact:true}).click()
  await page.screenshot({path:'test-results/scheduler-editor-inline.png', fullPage:true, animations:'disabled'})
  expect(errors).toEqual([])
})

test('调度卡片拖拽保持稳定，横向端口与类型颜色一致，位置可撤销并保存', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {localStorage.setItem('azurpilot.theme', 'light'); localStorage.setItem('azurpilot.language', 'zh-CN')})
  await page.goto('/#/i/demo-alt/task/SchedulerProgram')
  const card = page.locator('.react-flow__node[data-id="loop"]')
  await expect(card).toBeVisible()
  await page.locator('.program-canvas').scrollIntoViewIfNeeded()
  await page.evaluate(() => {
    const node = document.querySelector('.react-flow__node[data-id="loop"]')!
    ;(window as unknown as {dragNode:Element}).dragNode = node
  })
  const before = (await card.boundingBox())!
  const heading = (await card.locator('.program-card-heading').boundingBox())!
  await page.mouse.move(heading.x + heading.width / 2, heading.y + heading.height / 2)
  await page.mouse.down()
  for (let i = 1; i <= 12; i++) {
    await page.mouse.move(heading.x + heading.width / 2 + i * 5, heading.y + heading.height / 2 + i * 3)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const position = (await card.boundingBox())!
    expect(position.x).toBeCloseTo(before.x + i * 5, 0)
    expect(position.y).toBeCloseTo(before.y + i * 3, 0)
    expect(position.width).toBeCloseTo(before.width, 0)
    expect(await card.evaluate(node => node === (window as unknown as {dragNode:Element}).dragNode && getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).opacity === '1')).toBe(true)
  }
  // 跨过后台状态轮询周期，按住鼠标的卡片仍保持当前位置。
  await page.waitForTimeout(2200)
  expect((await card.boundingBox())!.x).toBeCloseTo(before.x + 60, 0)
  await page.mouse.up()
  await page.getByTitle('撤销', {exact:true}).click()
  expect((await card.boundingBox())!.x).toBeCloseTo(before.x, 0)
  await page.getByTitle('重做', {exact:true}).click()
  expect((await card.boundingBox())!.x).toBeCloseTo(before.x + 60, 0)
  const ports = await page.locator('.react-flow__node[data-id="run"]').evaluate(node => {
    const input = node.querySelector('[data-handleid="control:in"]')!, output = node.querySelector('[data-handleid="control:completed"]')!
    const task = node.querySelector('[data-handleid="data:task"]')!, result = node.querySelector('[data-handleid="data:result"]')!
    return {left:input.getBoundingClientRect().x, right:output.getBoundingClientRect().x, inputColor:getComputedStyle(input).backgroundColor, outputColor:getComputedStyle(output).backgroundColor, taskColor:getComputedStyle(task).backgroundColor, resultColor:getComputedStyle(result).backgroundColor}
  })
  expect(ports.right).toBeGreaterThan(ports.left)
  expect(ports.inputColor).toBe(ports.outputColor)
  expect(ports.taskColor).not.toBe(ports.resultColor)
  const colors = await page.locator('.program-card-heading').evaluateAll(nodes => [...new Set(nodes.map(n => getComputedStyle(n).backgroundColor))])
  expect(colors.length).toBeGreaterThanOrEqual(4)
  await card.locator('.program-card-heading').click()
  await page.getByLabel('卡片名称',{exact:true}).fill('日常循环')
  await page.getByLabel('卡片注释',{exact:true}).fill('每轮重新判断，不固定等待一分钟')
  await expect(card.locator('.program-card-heading strong')).toHaveText('条件 / 次数循环')
  await expect(card.locator('.program-card-alias')).toHaveText('名称：日常循环')
  await expect(card.locator('.program-card-comment')).toHaveText('每轮重新判断，不固定等待一分钟')
  await page.getByRole('button', {name:'保存草稿',exact:true}).click()
  await page.reload()
  await expect(card).toBeVisible()
  await expect(card.locator('.program-card-heading strong')).toHaveText('条件 / 次数循环')
  await expect(card.locator('.program-card-alias')).toHaveText('名称：日常循环')
  await expect(card.locator('.program-card-comment')).toHaveText('每轮重新判断，不固定等待一分钟')
  const persistedTransform = await card.getAttribute('style')
  expect(persistedTransform).not.toContain('translate(320px, 0px)')
  await page.screenshot({path:'test-results/scheduler-editor-colors.png', fullPage:true, animations:'disabled'})
  await page.setViewportSize({width:390,height:844})
  await page.getByRole('button', {name:'属性与连接',exact:true}).click()
  await expect(page.locator('.program-properties')).toBeVisible()
  await expect(page.locator('.program-library')).toBeHidden()
  await page.getByRole('button', {name:'卡片库',exact:true}).click()
  await expect(page.locator('.program-library')).toBeVisible()
  await page.screenshot({path:'test-results/scheduler-editor-mobile.png', fullPage:true, animations:'disabled'})
  expect(errors).toEqual([])
})

test('自定义调度从系统菜单进入，草稿、模拟与应用分离', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {localStorage.setItem('azurpilot.theme', 'light'); localStorage.setItem('azurpilot.language', 'zh-CN')})
  await page.goto('/#/i/demo-main/task/General')
  await expect(page.locator('[id="General.YukikazeTaskManager.TaskPriorityAdjustment"]')).toBeVisible()
  await page.locator('.field-row').filter({has:page.locator('[id="General.YukikazeTaskManager.TaskPriorityAdjustment"]')}).getByRole('link', {name:'自定义调度',exact:true}).click()
  await expect(page.locator('.program-editor h1')).toHaveText('自定义调度')
  await expect(page.locator('.program-toolbar small')).toContainText('当前使用原调度')
  await expect(page.getByRole('button',{name:'全卡片排列',exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'载入原调度方案',exact:true})).toBeVisible()
  await page.getByRole('button', {name:'载入原调度方案',exact:true}).click()
  await expect(page.locator('.react-flow__node[data-id="enabled"] .program-card-heading strong')).toHaveText('筛选任务列表')
  await expect(page.locator('.react-flow__node[data-id="enabled"] .program-card-comment')).toHaveText('只保留已启用任务')
  await expect(page.locator('.react-flow__node[data-id="due"] .program-card-comment')).toContainText('已到期')
  await expect(page.locator('.react-flow__node[data-id="order"] .program-card-comment')).toHaveText('按当前实例优先级排序')
  await page.getByRole('button', {name:'校验',exact:true}).click()
  await expect(page.locator('.program-diagnostics')).toHaveText('程序校验通过')
  await page.getByRole('button', {name:'模拟运行',exact:true}).click()
  await expect(page.locator('.program-trace')).toContainText('execute')
  await page.getByLabel('方案名称').fill('浏览器验收方案')
  await page.getByRole('button', {name:'保存草稿',exact:true}).click()
  await expect(page.locator('.program-toolbar small')).toContainText('当前使用原调度')
  await page.getByRole('button', {name:'应用方案',exact:true}).click()
  await expect(page.locator('.program-toolbar small')).toContainText('当前由卡片程序完全接管')
  await page.screenshot({path:'test-results/scheduler-editor-desktop.png', fullPage:true, animations:'disabled'})
  await page.reload()
  await expect(page.getByLabel('方案名称')).toHaveValue('浏览器验收方案')
  await page.getByRole('button', {name:'切回原调度',exact:true}).click()
  await expect(page.locator('.program-toolbar small')).toContainText('当前使用原调度')
  expect(errors).toEqual([])
})

test('任务分组目录重复点击保持在同一栏目', async ({page}) => {
  await page.emulateMedia({reducedMotion: 'reduce'})
  await page.addInitScript(() => localStorage.setItem('azurpilot.theme', 'light'))
  await page.setViewportSize({width: 1440, height: 600})
  await page.goto('/#/i/demo-main/task/Main')
  const links = page.locator('.config-layout .group-nav a')
  await expect(links.nth(1)).toBeVisible()
  await links.nth(1).click()
  await expect.poll(() => page.evaluate(() => document.scrollingElement!.scrollTop)).toBeGreaterThan(0)
  const firstPosition = await page.evaluate(() => document.scrollingElement!.scrollTop)
  await links.nth(1).click()
  await expect.poll(() => page.evaluate(() => document.scrollingElement!.scrollTop)).toBeCloseTo(firstPosition, 0)
})

test('玻璃装饰不阻挡导航，背景失败降级并尊重减少动态效果', async ({page}) => {
  let backgrounds = 0
  await page.route('https://api.yppp.net/api.php', async route => {
    backgrounds += 1
    await route.fulfill({contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#9acbff"/></svg>'})
  })
  await page.goto('/')
  await expect(page.locator('.wallpaper img')).toBeVisible()
  await expect(page.locator('.glass-material-lens')).toHaveCount(1)
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', {name: '跳转到内容'})).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('main')).toBeFocused()
  await page.locator('.instance-card').first().click()
  await page.getByRole('button', {name: '切换实例'}).click()
  await expect(page.getByRole('menuitemradio').first()).toBeVisible()
  await page.keyboard.press('Escape')
  expect(backgrounds).toBe(1)
  await page.emulateMedia({reducedMotion: 'reduce'})
  await expect(page.locator('.glass-material-lens')).toHaveCount(0)
  await expect(page.getByRole('button', {name: '切换实例'})).toBeVisible()
  await page.unroute('https://api.yppp.net/api.php')
  await page.route('https://api.yppp.net/api.php', route => route.abort())
  await page.reload()
  await expect(page.locator('.wallpaper img')).toHaveCount(0)
  await expect(page.getByRole('heading', {name: 'demo-main', exact: true})).toBeVisible()
})

test('总览三态、资源搭配记忆、日志与被动截图切换', async ({page}) => {
  const methods: string[] = []
  page.on('websocket', socket => socket.on('framesent', frame => { methods.push(JSON.parse(String(frame.payload)).method) }))
  await page.goto('/#/i/demo-main/overview')
  await expect(page.getByLabel('搜索日志')).toHaveCount(0)
  await expect(page.locator('.primary-nav').getByRole('link', {name: '运行日志'})).toHaveCount(0)
  await page.getByRole('button', {name: '仪表盘设置', exact: true}).click()
  const settings = page.getByRole('dialog')
  await settings.getByRole('button', {name: '添加卡片', exact: true}).click()
  await settings.getByRole('button', {name: '行动力', exact: true}).click()
  const editorCards = settings.locator('.resource-editor-card:not(.resource-editor-add)')
  const source = await editorCards.last().boundingBox()
  const target = await editorCards.first().boundingBox()
  expect(source).not.toBeNull()
  expect(target).not.toBeNull()
  await page.mouse.move(source!.x + source!.width / 2, source!.y + source!.height / 2)
  await page.mouse.down()
  await page.mouse.move(target!.x + target!.width / 2, target!.y + target!.height / 2, {steps: 5})
  await page.mouse.up()
  await expect(editorCards.first()).toContainText('行动力')
  await settings.getByRole('button', {name: '关闭', exact: true}).click()
  await expect(page.locator('.resource-card')).toHaveCount(5)
  await expect(page.locator('.resource-card').first()).toContainText('行动力')
  const actionPoint = page.locator('.resource-card').filter({hasText: '行动力'})
  await expect(actionPoint.locator('.resource-heading')).toHaveText('行动力')
  await expect(actionPoint.locator('.resource-value')).toHaveText('101/ 5,301')
  await expect(actionPoint.locator('.resource-value small')).toHaveText('/ 5,301')
  await expect(actionPoint.locator('.resource-icon-image')).toHaveAttribute('src', /guild_coin\.webp/)
  await page.reload()
  await expect(page.locator('.resource-card')).toHaveCount(5)
  await page.getByRole('button', {name: '启动调度器', exact: true}).click()
  await expect(page.locator('.task-state.running')).toHaveCount(1)
  await expect(page.locator('.task-state.pending').first()).toBeVisible()
  await expect(page.locator('.task-state.waiting').first()).toBeVisible()
  await page.getByRole('tab', {name: '截图', exact: true}).click()
  await expect(page.getByAltText('任务最近一次截图')).toBeVisible({timeout: 10000})
  expect(methods).not.toContain('preview.capture')
  await page.screenshot({path: 'test-results/overview-preview-new.png', fullPage: true})
  await page.getByRole('tab', {name: '日志', exact: true}).click()
  const logContent = page.getByLabel('日志内容')
  await logContent.evaluate(element => { element.setAttribute('style', 'flex: 0 0 24px; height: 24px; min-height: 0') })
  await expect.poll(() => logContent.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true)
  await logContent.evaluate(element => { element.scrollTop = 0 })
  await expect.poll(() => logContent.evaluate(element => element.scrollTop + element.clientHeight >= element.scrollHeight - 1), {timeout: 5000}).toBe(true)
  await page.getByRole('button', {name: '展开日志筛选'}).click()
  await page.getByLabel('搜索日志').fill('模拟调度器已启动')
  await expect(page.locator('.log-line')).toHaveCount(1)
  await page.getByRole('button', {name: '停止运行', exact: true}).click()
  await page.getByLabel('搜索日志').fill('')
  await page.screenshot({path: 'test-results/overview-logs-new.png', fullPage: true})
  await page.goto('/#/i/demo-main/task/Main')
  await expect(page.locator('[id="Main.Emotion.Fleet1Record"]')).toHaveValue('2026-09-12 23:45:12.123456')
  await expect(page.locator('[id="Main.Emotion.Fleet1Record"]')).toHaveAttribute('readonly', '')
})

test('资源数值按可用宽度缩放并保持当前值与上限在同一行', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.resources.demo-main', JSON.stringify(['Oil', 'Coin', 'Gem', 'Cube', 'Pt', 'ActionPoint', 'YellowCoin', 'PurpleCoin', 'Core', 'Medal', 'Merit', 'GuildCoin']))
    if (!localStorage.getItem('azurpilot.theme')) localStorage.setItem('azurpilot.theme', 'legacy-light')
  })
  await page.setViewportSize({width: 1996, height: 900})
  await page.goto('/#/i/demo-main/overview')
  const values = page.locator('.resource-value')
  await expect(values).toHaveCount(12)
  const coin = page.locator('.resource-card').filter({hasText: '物资'}).locator('.resource-value-content')
  await expect(coin).toHaveText('186,420/ 600,000')
  const assertFits = async () => {
    await expect.poll(() => values.evaluateAll(elements => elements.every(element => {
      const content = element.querySelector('.resource-value-content')!
      const primary = content.querySelector('span')!
      const suffix = content.querySelector('small')
      const box = content.getBoundingClientRect()
      return box.width <= element.clientWidth + .5
        && (!suffix || (suffix.getClientRects().length === 1
          && suffix.getBoundingClientRect().top < primary.getBoundingClientRect().bottom
          && parseFloat(getComputedStyle(suffix).fontSize) < parseFloat(getComputedStyle(primary).fontSize)))
    }))).toBe(true)
  }
  await assertFits()
  await expect.poll(() => coin.evaluate(element => parseFloat(getComputedStyle(element).fontSize) < parseFloat(getComputedStyle(element.parentElement!).fontSize))).toBe(true)
  await page.locator('.resource-grid').screenshot({path: 'test-results/resource-values-desktop.png'})
  await page.setViewportSize({width: 390, height: 844})
  await page.evaluate(() => localStorage.setItem('azurpilot.theme', 'light'))
  await page.reload()
  await expect(values).toHaveCount(12)
  await assertFits()
  await page.locator('.resource-grid').screenshot({path: 'test-results/resource-values-mobile.png'})
  // 宽度恢复后应还原主题字号，避免只缩小不放大。
  await page.setViewportSize({width: 3000, height: 1000})
  await assertFits()
  await expect.poll(() => coin.evaluate(element => getComputedStyle(element).fontSize === getComputedStyle(element.parentElement!).fontSize)).toBe(true)
  expect(errors).toEqual([])
})

for (const theme of ['minimal', 'legacy-light', 'legacy-dark', 'extreme'] as const) {
  test(`${theme} 窄屏总览与统计内容完整可访问`, async ({page}) => {
    test.setTimeout(60000)
    await page.addInitScript(value => localStorage.setItem('azurpilot.theme', value), theme)
    await page.setViewportSize({width: 550, height: 1000})
    await page.goto('/#/i/demo-main/overview')
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const legacy = theme.startsWith('legacy-')
    await expect(page.locator('.resource-card')).toHaveCount(4)
    await expect.poll(() => page.locator('main').evaluate(element => element.clientHeight)).toBeGreaterThan(500)
    if (!legacy) await page.getByRole('button', {name: '打开调度与任务', exact: true}).click()
    await page.getByRole('button', {name: '启动调度器', exact: true}).click()
    if (!legacy) await page.locator('.right-rail').getByRole('button', {name: '关闭调度与任务', exact: true}).click()
    try {
      await page.getByRole('tab', {name: '截图', exact: true}).click()
      const preview = page.getByAltText('任务最近一次截图')
      await expect(preview).toBeVisible({timeout: 10000})
      for (const width of [900, 550, 390]) {
        await page.setViewportSize({width, height: 1000})
        await preview.scrollIntoViewIfNeeded()
        await expect(preview).toBeInViewport({ratio: .95})
        expect((await preview.boundingBox())!.height).toBeGreaterThan(100)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      }
      await page.screenshot({path: `test-results/narrow-${theme}-overview.png`, fullPage: true})
    } finally {
      if (!legacy) await page.getByRole('button', {name: '打开调度与任务', exact: true}).click()
      await page.getByRole('button', {name: '停止运行', exact: true}).click()
      if (!legacy) await page.locator('.right-rail').getByRole('button', {name: '关闭调度与任务', exact: true}).click()
    }

    await page.goto('/#/i/demo-main/statistics')
    for (const width of [900, 550, 390]) {
      await page.setViewportSize({width, height: 1000})
      await page.getByRole('button', {name: '打开导航', exact: true}).click()
      await expect(page.locator('.sidebar')).toBeInViewport({ratio: .95})
      await page.getByRole('button', {name: '关闭导航', exact: true}).click()
      if (!legacy) {
        await page.getByRole('button', {name: '打开调度与任务', exact: true}).click()
        await expect(page.locator('.right-rail')).toBeInViewport({ratio: .95})
        await page.locator('.right-rail').getByRole('button', {name: '关闭调度与任务', exact: true}).click()
      }
      for (const category of ['资源趋势', '大世界趋势', '短猫掉落']) {
        const picker = page.getByRole('combobox', {name: '统计分类', exact: true})
        if (await picker.isVisible()) {
          await picker.click()
          await page.getByRole('option', {name: category, exact: true}).click()
        } else {
          await page.getByRole('tab', {name: category, exact: true}).click()
        }
        const content = page.locator(category === '短猫掉落' ? '.statistics-table' : '.chart-canvas').first()
        await expect(content).toBeVisible()
        await content.scrollIntoViewIfNeeded()
        await expect(content).toBeInViewport({ratio: .95})
        await expect.poll(() => page.locator('.statistics-sections').evaluate(element => element.clientHeight)).toBeGreaterThan(200)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      }
    }
    await page.screenshot({path: `test-results/narrow-${theme}-statistics.png`, fullPage: true})
  })
}

test('任务二级菜单通过顶层浮层覆盖资源卡片', async ({page}) => {
  await page.setViewportSize({width: 1134, height: 669})
  await page.addInitScript(() => localStorage.setItem('azurpilot.resources.demo-main', JSON.stringify(['Oil', 'ActionPoint'])))
  await page.goto('/#/i/demo-main/overview')
  await page.locator('.task-group-button').filter({hasText: '系统'}).click()
  const flyout = page.locator('.task-submenu-flyout')
  await expect(flyout).toBeVisible()
  await expect(flyout).toHaveCSS('position', 'fixed')
  await expect(flyout).toHaveCSS('z-index', '100')
  await expect(flyout).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(flyout).toHaveCSS('backdrop-filter', 'none')
  expect(await flyout.evaluate(element => element.parentElement === document.body)).toBe(true)

  const overlap = await flyout.evaluate(element => {
    const flyoutRect = element.getBoundingClientRect()
    const card = [...document.querySelectorAll<HTMLElement>('.resource-card')].find(candidate => {
      const rect = candidate.getBoundingClientRect()
      return Math.max(flyoutRect.left, rect.left) < Math.min(flyoutRect.right, rect.right) && Math.max(flyoutRect.top, rect.top) < Math.min(flyoutRect.bottom, rect.bottom)
    })
    if (!card) return {found: false, onTop: false}
    const cardRect = card.getBoundingClientRect()
    const x = (Math.max(flyoutRect.left, cardRect.left) + Math.min(flyoutRect.right, cardRect.right)) / 2
    const y = (Math.max(flyoutRect.top, cardRect.top) + Math.min(flyoutRect.bottom, cardRect.bottom)) / 2
    return {found: true, onTop: !!document.elementFromPoint(x, y) && element.contains(document.elementFromPoint(x, y))}
  })
  expect(overlap).toEqual({found: true, onTop: true})
  await page.screenshot({path: 'test-results/task-submenu-resource-overlay.png', fullPage: true, animations: 'disabled'})
})

test('舰队扫描和半自动工具在当前页面显示运行日志', async ({page}) => {
  for (const {instance, task, title} of [
    {instance: 'demo-main', task: 'FleetScan', title: '舰队扫描'},
    {instance: 'demo-alt', task: 'Daemon', title: '半自动点击'},
  ]) {
    const path = `/#/i/${instance}/task/${task}`
    await page.goto(path)

    const heading = page.locator('.page-title h1')
    const logs = page.getByLabel('日志内容')
    await expect(heading).toHaveAccessibleName(title)
    await expect(logs).toBeVisible()
    expect((await logs.boundingBox())!.y).toBeGreaterThan((await heading.boundingBox())!.y)

    await page.getByRole('button', {name: '运行工具', exact: true}).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    let running = false
    try {
      await dialog.getByRole('button', {name: '确认运行', exact: true}).click()
      running = true
      await expect(page).toHaveURL(new RegExp(`/i/${instance}/task/${task}$`))
      await expect(logs).toContainText('模拟调度器已启动')
      if (task === 'FleetScan') await page.screenshot({path: 'test-results/tool-run-log.png', fullPage: true})
    } finally {
      if (running) {
        const stop = page.getByRole('button', {name: '停止运行', exact: true})
        await expect(stop).toBeVisible()
        await stop.click()
        await expect(page.getByRole('button', {name: '启动调度器', exact: true})).toBeVisible()
      }
    }
  }
})

test('分段滑块首屏静止，交互后平移并尊重减少动态效果', async ({page}) => {
  await page.addInitScript(() => {
    document.addEventListener('transitionrun', event => {
      if (event.target instanceof Element && event.target.matches('.segmented-indicator')) {
        const root = document.documentElement
        root.dataset.segmentTransitions = String(Number(root.dataset.segmentTransitions ?? 0) + 1)
      }
    })
  })
  await page.goto('/#/i/demo-main/statistics')
  await expect(page.getByRole('img', {name: '石油交互趋势图'})).toBeVisible()
  const tabs = page.getByRole('tablist', {name: '统计分类'})
  const transitions = () => page.evaluate(() => Number(document.documentElement.dataset.segmentTransitions ?? 0))
  expect(await transitions()).toBe(0)
  await tabs.screenshot({path: 'test-results/segmented-statistics-light.png'})
  await tabs.getByRole('tab', {name: '委托收益', exact: true}).click()
  await expect.poll(transitions).toBeGreaterThan(0)
  await expect(page.locator('.period-controls strong')).toHaveText('委托收益')
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'))
  await expect(tabs).toHaveCSS('background-color', 'rgba(37, 37, 41, 0.78)')
  await expect(tabs.getByRole('tab', {name: '委托收益', exact: true})).toHaveCSS('color', 'rgb(245, 245, 247)')
  await tabs.screenshot({path: 'test-results/segmented-statistics-dark.png'})
  await page.emulateMedia({reducedMotion: 'reduce'})
  const before = await transitions()
  await tabs.getByRole('tab', {name: '大世界总结', exact: true}).click()
  await expect(page.locator('.period-controls strong')).toHaveText('大世界总结')
  expect(await transitions()).toBe(before)
  await expect(tabs.locator('.segmented-indicator')).toHaveCSS('transition-duration', '0s')
})

test('统计与监控复用分段控件的样式及键盘切换', async ({page}) => {
  await page.goto('/#/i/demo-main/overview')
  const monitor = page.getByRole('tablist', {name: '监控视图'})
  await expect(monitor).toBeVisible()
  await monitor.screenshot({path: 'test-results/segmented-monitor-light.png'})
  const appearance = await monitor.evaluate(control => {
    const style = getComputedStyle(control)
    return [style.backgroundColor, style.borderColor, style.borderRadius, control.querySelector('button')!.getBoundingClientRect().height]
  })
  await monitor.getByRole('tab', {name: '日志', exact: true}).focus()
  await page.keyboard.press('ArrowRight')
  await expect(monitor.getByRole('tab', {name: '截图', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.preview-screen')).toBeVisible()
  await page.keyboard.press('ArrowLeft')
  await expect(monitor.getByRole('tab', {name: '日志', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.preview-screen')).toBeHidden()
  await page.goto('/#/i/demo-main/statistics')
  const statistics = page.getByRole('tablist', {name: '统计分类'})
  await expect(statistics).toBeVisible()
  expect(await statistics.evaluate(control => {
    const style = getComputedStyle(control)
    return [style.backgroundColor, style.borderColor, style.borderRadius, control.querySelector('button')!.getBoundingClientRect().height]
  })).toEqual(appearance)
})

test('统计分类、K 线、时间过滤、表格导出与移动端布局', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/i/demo-main/statistics')
  await expect(page.getByRole('img', {name: '石油交互趋势图'})).toBeVisible()
  const rawRecords = page.locator('.statistics-chart .statistics-table tbody tr')
  const recordTime = async (row: ReturnType<typeof rawRecords.first>) => Date.parse((await row.locator('td').first().innerText()).replace(' ', 'T'))
  await expect(rawRecords).toHaveCount(24)
  expect(await recordTime(rawRecords.first())).toBeGreaterThan(await recordTime(rawRecords.last()))
  const timeColumn = page.locator('.statistics-chart .statistics-table th').first()
  await expect(timeColumn).toHaveAttribute('aria-sort', 'descending')
  await timeColumn.getByRole('button').click()
  await expect(timeColumn).toHaveAttribute('aria-sort', 'ascending')
  expect(await recordTime(rawRecords.first())).toBeLessThan(await recordTime(rawRecords.last()))
  await page.getByRole('combobox', {name: '图表类型', exact: true}).click()
  await page.getByRole('option', {name: 'K 线（开高低收）', exact: true}).click()
  await page.getByRole('combobox', {name: '采样粒度', exact: true}).click()
  await page.getByRole('option', {name: '每小时', exact: true}).last().click()
  await page.screenshot({path: 'test-results/statistics-candlestick.png', fullPage: true})
  const download = page.waitForEvent('download')
  await page.getByRole('button', {name: '导出本类数据'}).click()
  expect((await download).suggestedFilename()).toMatch(/\.csv$/)
  for (const label of ['大世界趋势', '大世界总结', '委托收益', '舰船经验', '短猫掉落']) {
    await page.getByRole('tablist', {name: '统计分类'}).getByRole('tab', {name: label, exact: true}).click()
    await expect(page.locator('.period-controls strong')).toHaveText(label)
  }
  await page.getByRole('tab', {name: '资源趋势', exact: true}).click()
  await page.getByLabel('起始时间').fill('2099-01-01T00:00')
  await expect(page.getByText('这段时间没有有效记录')).toBeVisible()
  await page.getByRole('button', {name: '全部时间', exact: true}).click()
  await page.getByRole('combobox', {name: '图表类型', exact: true}).click()
  await page.getByRole('option', {name: 'K 线（开高低收）', exact: true}).click()
  await page.screenshot({path: 'test-results/statistics-resources-new.png', fullPage: true})
  await page.setViewportSize({width: 390, height: 844})
  const tabs = page.getByRole('tablist', {name: '统计分类'})
  await tabs.getByRole('tab', {name: '资源趋势', exact: true}).focus()
  await page.keyboard.press('End')
  await expect(tabs.getByRole('tab', {name: '科研掉落', exact: true})).toBeFocused()
  await expect(tabs.getByRole('tab', {name: '科研掉落', exact: true})).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.period-controls strong')).toHaveText('科研掉落')
  await expect.poll(() => tabs.evaluate(control => {
    const active = control.querySelector('[aria-selected="true"]')!.getBoundingClientRect()
    const indicator = control.querySelector('.segmented-indicator')!.getBoundingClientRect()
    return Math.abs(active.x - indicator.x) + Math.abs(active.width - indicator.width)
  })).toBeLessThan(1)
  await page.keyboard.press('ArrowRight')
  await expect(tabs.getByRole('tab', {name: '资源趋势', exact: true})).toBeFocused()
  await expect(page.getByRole('img', {name: '石油交互趋势图'})).toBeVisible()
  await page.screenshot({path: 'test-results/statistics-mobile-new.png', fullPage: true})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(errors).toEqual([])
})

test('下拉切换实例、创建入口与实例隔离', async ({page}) => {
  await page.goto('/#/i/demo-main/task/Alas')
  const serial = page.locator('[id="Alas.Emulator.Serial"]')
  await expect(serial).toHaveValue('127.0.0.1:5555')
  await expect(page.locator('.rail')).toHaveCount(0)
  await expect(page.locator('.primary-nav').getByRole('link', {name: '系统设置'})).toHaveCount(0)
  await expect(page.getByRole('button', {name: /保存/})).toHaveCount(0)
  await expect(page.getByRole('button', {name: '撤销修改'})).toHaveCount(0)
  await page.getByRole('button', {name: '切换实例'}).click()
  await page.getByRole('menuitemradio', {name: 'demo-alt', exact: true}).click()
  await expect(page).toHaveURL(/demo-alt\/task\/Alas/)
  await page.goto('/#/i/demo-alt/task/Alas')
  await expect(serial).toHaveValue('127.0.0.1:5557')
  await page.getByRole('button', {name: '切换实例'}).click()
  await page.keyboard.press('End')
  await expect(page.getByRole('menuitem', {name: '创建实例'})).toBeFocused()
  await page.keyboard.press('Enter')
  const name = `mock_${Date.now()}`
  await page.getByRole('dialog').getByLabel('实例名称', {exact: true}).fill(name)
  await page.getByRole('dialog').getByRole('button', {name: '创建实例', exact: true}).click()
  await expect(page).toHaveURL(new RegExp(`${name}/task/Alas`))
  await expect(serial).toBeVisible()
})

test('配置字体、多行输入与 YAML 编辑实时保存及主题颜色', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/i/demo-main/task/Alas')
  const editor = page.locator('[id="Alas.Error.OnePushConfig"]')
  await expect(editor).toBeVisible()
  await expect(page.locator('.field-label small')).toHaveCount(0)
  expect(await page.locator('.field-label label').first().evaluate(node => parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(14)
  expect(await page.locator('html').evaluate(node => getComputedStyle(node).zoom || '1')).toBe('1')
  const row = editor.locator('xpath=ancestor::div[contains(@class,"field-row")]')
  const label = await row.locator('.field-label').boundingBox()
  const input = await row.locator('.field-control').boundingBox()
  expect(input!.y).toBeGreaterThan(label!.y + label!.height)
  expect(input!.width).toBeGreaterThan(500)
  const yaml = '# 通知配置\nprovider: null\nretry: 3\nenabled: true\nmessage: "测试颜色"'
  await editor.fill(yaml)
  await page.waitForTimeout(500)
  await page.reload()
  await expect(editor).toHaveText(yaml.replaceAll('\n', ''))
  const token = editor.locator('span').filter({hasText: /^provider$/}).first()
  const lightColor = await token.evaluate(node => getComputedStyle(node).color)
  await row.scrollIntoViewIfNeeded()
  await page.screenshot({path: 'test-results/yaml-light.png'})
  await page.goto('/#/interface')
  await page.getByRole('combobox', {name: '界面主题', exact: true}).click()
  await page.getByRole('option', {name: '深色', exact: true}).click()
  await page.goto('/#/i/demo-main/task/Alas')
  await expect(editor).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await token.evaluate(node => getComputedStyle(node).color)).not.toBe(lightColor)
  await row.scrollIntoViewIfNeeded()
  await page.screenshot({path: 'test-results/yaml-dark.png'})
  const textarea = page.locator('textarea').first()
  await expect(textarea).toBeVisible()
  expect((await textarea.boundingBox())!.height).toBeLessThan(80)
  expect(errors).toEqual([])
})

test('受限 Lua 策略保留本地草稿，检查通过后才可应用', async ({page}) => {
  await page.goto('/#/i/demo-main/task/EventShop')
  const script = page.locator('[id="EventShop.ShopAdvanced.Script"]')
  const check = page.getByRole('button', {name: '检查', exact: true})
  const apply = page.getByRole('button', {name: '应用', exact: true})
  await expect(page.getByText('高级商店策略说明', {exact: true})).toBeVisible()
  await expect(page.getByText('context.domain', {exact: true})).toHaveCount(1)
  await page.screenshot({path: 'test-results/restricted-lua-help.png', fullPage: true})
  await expect(apply).toBeDisabled()

  await script.fill('os.execute("bad")')
  await check.click()
  await expect(page.getByText('不允许调用 os.execute', {exact: true})).toBeVisible()
  await expect(page.getByText('位置 1:1', {exact: true})).toBeVisible()
  await expect(apply).toBeDisabled()

  const valid = 'return shop.plan { candidates = candidates:take(0) }'
  await script.fill(valid)
  await expect(apply).toBeDisabled()
  await check.click()
  await expect(apply).toBeEnabled()
  await apply.click()
  await page.reload()
  await expect(script).toHaveText(valid)
  await page.setViewportSize({width: 390, height: 844})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({path: 'test-results/restricted-lua-mobile.png', fullPage: true})
})

test('输入框随内容和宽度变化增高，删除后缩回单行', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/i/demo-alt/task/Alas')
  const input = page.locator('textarea').first()
  await expect(input).toBeVisible()
  await input.fill('单行')
  const single = (await input.boundingBox())!.height
  expect(single).toBeLessThan(80)
  await input.fill('第一行\n第二行\n第三行\n第四行')
  expect((await input.boundingBox())!.height).toBeGreaterThan(single + 70)
  await input.fill('单行')
  expect((await input.boundingBox())!.height).toBeCloseTo(single, 0)
  await input.fill('宽度变化会触发重新计算高度。'.repeat(25))
  const wide = (await input.boundingBox())!.height
  await page.setViewportSize({width: 390, height: 844})
  await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(wide)
  await input.fill('单行')
  const mobileSingle = (await input.boundingBox())!.height
  expect(mobileSingle).toBeLessThan(80)
  await input.fill('')
  expect((await input.boundingBox())!.height).toBeCloseTo(mobileSingle, 0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.setViewportSize({width: 1440, height: 1100})
  const yaml = page.locator('[id="Alas.Error.OnePushConfig"]')
  const scroller = yaml.locator('xpath=ancestor::div[contains(@class,"cm-scroller")]')
  const yamlSingle = (await scroller.boundingBox())!.height
  expect(yamlSingle).toBeLessThan(80)
  await yaml.fill('provider: null\nretry: 3\nenabled: true\nmessage: 测试')
  expect((await scroller.boundingBox())!.height).toBeGreaterThan(yamlSingle + 70)
  await yaml.fill('provider: null')
  expect((await scroller.boundingBox())!.height).toBeCloseTo(yamlSingle, 0)
  expect(errors).toEqual([])
})

test('存储空间为空时隐藏，有状态时显示完整 JSON 并可清除', async ({page}) => {
  await page.goto('/#/i/demo-alt/task/Alas')
  await expect(page.locator('textarea').first()).toBeVisible()
  await expect(page.locator('#group-Storage')).toHaveCount(0)
  await expect(page.locator('.group-nav').getByRole('link', {name: '任务状态'})).toHaveCount(0)
  await page.getByRole('textbox', {name: '搜索配置项', exact: true}).fill('Storage.Storage')
  await expect(page.getByText('没有找到配置项')).toBeVisible()
  await page.goto('/#/i/demo-error/task/Alas')
  await page.getByRole('textbox', {name: '搜索配置项', exact: true}).fill('')
  const storage = page.getByLabel('存储空间内容')
  await expect(storage).toBeVisible()
  expect(JSON.parse(await storage.innerText())).toEqual({failureCount: 3, lastError: '模拟器连接失败', retry: {enabled: false, remaining: 0}, tasks: ['Commission', 'Research']})
  await expect(storage).not.toContainText('[object Object]')
  const serial = page.locator('[id="Alas.Emulator.Serial"]')
  await serial.fill('保留其他字段的更改')
  await page.locator('#group-Storage').scrollIntoViewIfNeeded()
  await page.screenshot({path: 'test-results/storage-state.png', animations: 'disabled'})
  await page.getByRole('button', {name: '清除存储空间'}).click()
  await expect(page.locator('#group-Storage')).toHaveCount(0)
  await expect(page.locator('.group-nav').getByRole('link', {name: '任务状态'})).toHaveCount(0)
  await expect(serial).toHaveValue('保留其他字段的更改')
  await page.reload()
  await expect(page.locator('textarea').first()).toBeVisible()
  await expect(page.locator('#group-Storage')).toHaveCount(0)
})

test('侧栏任务计划随界面语言切换', async ({page}) => {
  await page.goto('/#/interface')
  await page.locator('#ui-language').click()
  await page.getByRole('option', {name: 'English', exact: true}).click()
  await page.goto('/#/i/demo-main/overview')
  await expect(page.locator('.rail-task-item[href$="/task/Commission"]')).toContainText('Commission')
  await expect(page.locator('.rail-task-item[href$="/task/Research"]')).toContainText('Research Lab Plus')
})

test('语言偏好持久化，模拟启停、预览、统计和部署设置', async ({page}) => {
  await page.goto('/#/interface')
  await page.locator('#ui-language').click()
  await page.getByRole('option', {name: 'English', exact: true}).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
  await page.reload()
  await expect(page.locator('#ui-language')).toHaveText('English')
  await expect(page.getByRole('heading', {name: 'Interface', exact: true})).toBeVisible()
  await expect(page.locator('.primary-nav').getByRole('link', {name: 'Updater', exact: true})).toBeVisible()
  await page.goto('/#/i/demo-main/task/Alas')
  await expect(page.locator('label[for="Alas.Emulator.Serial"]')).toContainText(/serial/i)
  await page.goto('/#/interface')
  await page.locator('#ui-language').click()
  await page.getByRole('option', {name: '简体中文', exact: true}).click()
  await page.goto('/#/remote')
  await page.getByLabel('监听端口').fill('23456')
  await page.waitForTimeout(500)
  await page.reload()
  await expect(page.getByLabel('监听端口')).toHaveValue('23456')
  await page.goto('/#/i/demo-main/overview')
  await page.getByRole('button', {name: '启动调度器'}).click()
  await expect(page.getByRole('button', {name: '停止运行'})).toBeVisible()
  await expect(page.locator('.log-content')).toContainText('模拟调度器已启动')
  await page.getByRole('tab', {name: '截图', exact: true}).click()
  await expect(page.getByRole('img', {name: '任务最近一次截图'})).toBeVisible()
  await page.screenshot({path: 'test-results/mock-overview.png', fullPage: true})
  await page.getByRole('button', {name: '停止运行'}).click()
  await page.locator('.primary-nav').getByRole('link', {name: '资源统计'}).click()
  await expect(page.getByRole('img', {name: /交互趋势图/})).toBeVisible()
})

test('移动端放大布局无横向溢出，单栏导航可以收起', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844})
  await page.goto('/#/i/demo-main/overview')
  await page.getByRole('button', {name: '切换实例'}).click()
  await page.getByRole('menuitemradio', {name: 'demo-alt', exact: true}).click()
  await expect(page.locator('.app-shell')).not.toHaveClass(/mobile-open/)
  await page.getByRole('button', {name: '打开导航'}).click()
  await page.getByRole('link', {name: 'AzurPilot 主页'}).click()
  await page.getByRole('button', {name: '打开导航'}).click()
  await page.locator('.primary-nav').getByRole('link', {name: '界面设置'}).click()
  await expect(page.getByLabel('界面主题')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({path: 'test-results/mock-mobile.png', fullPage: true, animations: 'disabled'})
})

test('窄窗口调度器入口位于左侧标题栏且可展开右栏', async ({page}) => {
  await page.setViewportSize({width: 950, height: 844})
  await page.goto('/#/i/demo-main/overview')
  const topbar = page.locator('.topbar')
  const toggle = page.getByRole('button', {name: '打开调度与任务'})
  await expect(toggle).toBeVisible()
  const [toggleBox, topbarBox] = await Promise.all([toggle.boundingBox(), topbar.boundingBox()])
  expect(toggleBox!.y).toBeGreaterThanOrEqual(topbarBox!.y)
  expect(toggleBox!.y + toggleBox!.height).toBeLessThanOrEqual(topbarBox!.y + topbarBox!.height)
  expect(toggleBox!.x + toggleBox!.width).toBeLessThanOrEqual(topbarBox!.x + topbarBox!.width / 2)
  await toggle.click()
  await expect(page.locator('.app-shell')).toHaveClass(/rail-open/)
  await expect(page.locator('.right-rail')).toBeVisible()
  await page.locator('.mobile-rail-toggle').click()
  await expect(page.locator('.app-shell')).not.toHaveClass(/rail-open/)
  await page.setViewportSize({width: 213, height: 500})
  await expect(page.locator('.breadcrumb')).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.locator('.mobile-rail-toggle').click()
  await expect(page.locator('.right-rail')).toBeVisible()
  await page.locator('.right-rail').getByRole('button', {name: '关闭调度与任务'}).click()
  await expect(page.locator('.app-shell')).not.toHaveClass(/rail-open/)
  await page.setViewportSize({width: 951, height: 844})
  await expect(page.locator('.mobile-rail-toggle')).toBeHidden()
})

test('移动端窄屏下调度程序支持画布、卡片库与属性三态切换与调试抽屉适配', async ({page}) => {
  await page.setViewportSize({width: 414, height: 896})
  await page.goto('/#/i/demo-alt/task/SchedulerProgram')
  await expect(page.locator('.program-editor')).toBeVisible()
  const mobileEditorBox = (await page.locator('.program-editor').boundingBox())!
  const mobileTopbarBox = (await page.locator('.topbar').boundingBox())!
  expect(Math.abs(mobileEditorBox.x - mobileTopbarBox.x)).toBeLessThan(1)
  const mobileNav = page.locator('.program-mobile-panels')
  await expect(mobileNav).toBeVisible()
  const canvasBtn = mobileNav.getByRole('button', {name: '画布', exact: true})
  const libraryBtn = mobileNav.getByRole('button', {name: '卡片库', exact: true})
  const propertiesBtn = mobileNav.getByRole('button', {name: '属性与连接', exact: true})

  // 默认在移动端展示画布，左右浮层收起，全屏沉浸
  await expect(canvasBtn).toHaveClass(/active/)
  await expect(page.locator('.program-library')).toBeHidden()
  await expect(page.locator('.program-properties')).toBeHidden()
  await expect(page.locator('.program-canvas')).toBeVisible()

  // 切换到卡片库，验证全屏实体面板与返回画布按钮
  await libraryBtn.click()
  await expect(libraryBtn).toHaveClass(/active/)
  await expect(page.locator('.program-library')).toBeVisible()
  await expect(page.locator('.program-properties')).toBeHidden()
  const libBack = page.locator('.program-library .program-mobile-back')
  await expect(libBack).toBeVisible()
  await page.screenshot({path: 'test-results/scheduler-mobile-library.png'})
  await libBack.click()
  await expect(canvasBtn).toHaveClass(/active/)

  // 再次切换到卡片库，点击添加卡片后自动切回画布
  await libraryBtn.click()
  await page.locator('.program-library').getByRole('button', {name: '读取资源', exact: true}).click()
  await expect(canvasBtn).toHaveClass(/active/)
  await expect(page.locator('.program-canvas')).toBeVisible()

  // 切换到属性与连接面板，验证全屏面板与返回画布按钮
  await propertiesBtn.click()
  await expect(propertiesBtn).toHaveClass(/active/)
  await expect(page.locator('.program-properties')).toBeVisible()
  await expect(page.locator('.program-library')).toBeHidden()
  const propBack = page.locator('.program-properties .program-mobile-back')
  await expect(propBack).toBeVisible()
  await page.screenshot({path: 'test-results/scheduler-mobile-properties.png'})
  await propBack.click()
  await expect(canvasBtn).toHaveClass(/active/)

  // 移动端展开调试抽屉并截图
  await page.getByRole('button', {name: '调试', exact: true}).click()
  const drawer = page.locator('.program-console')
  await expect(drawer).toBeVisible()
  await page.waitForTimeout(300)
  const drawerBox = (await drawer.boundingBox())!
  expect(drawerBox.width).toBeGreaterThanOrEqual(380)
  await page.screenshot({path: 'test-results/scheduler-mobile-console.png'})

  // 移动端模拟运行并可关闭抽屉
  await page.getByRole('button', {name: '模拟运行', exact: true}).click()
  await expect(page.locator('.program-trace')).toBeVisible()
  await page.getByRole('button', {name: '关闭调试面板', exact: true}).click()
  await expect(drawer).toBeHidden()

  // 验证子工具栏支持移动端横向平滑滑动且不破坏视口
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({path: 'test-results/scheduler-mobile.png', fullPage: true})
})

test('调度程序在全量六套主题下背景与控件对比度正常无白底穿透', async ({page}) => {
  await page.goto('/#/i/demo-alt/task/SchedulerProgram')
  await expect(page.locator('.program-editor')).toBeVisible()

  // 1. 测试深色模式 (dark)
  await page.evaluate(() => {
    localStorage.setItem('azurpilot.theme', 'dark')
  })
  await page.reload()
  await expect(page.locator('.program-editor')).toBeVisible()
  const darkBg = await page.locator('.program-workspace').evaluate(el => getComputedStyle(el).backgroundColor)
  const darkRgb = darkBg.match(/\d+/g)?.map(Number) ?? [255, 255, 255]
  expect(darkRgb[0]).toBeLessThan(80)
  const darkEditorBox = (await page.locator('.program-editor').boundingBox())!
  const darkTopbarBox = (await page.locator('.topbar').boundingBox())!
  expect(Math.abs(darkEditorBox.x - darkTopbarBox.x)).toBeLessThan(1)
  expect(await page.locator('.program-editor').evaluate(el => getComputedStyle(el).borderTopLeftRadius)).toBe('26px')
  await page.screenshot({path: 'test-results/scheduler-theme-dark.png'})
  const entry = page.locator('.react-flow__node').filter({has: page.locator('.program-card-title', {hasText: '程序入口'})}).first()
  const entryBox = (await entry.boundingBox())!
  const libraryBox = (await page.locator('.program-library').boundingBox())!
  expect(entryBox.width).toBeGreaterThan(150)
  expect(entryBox.x).toBeGreaterThan(libraryBox.x + libraryBox.width)
  await expect(page.locator('.program-properties')).toBeHidden()
  await entry.click()
  await expect(page.locator('.program-properties')).toBeVisible()
  const selectedBox = (await entry.boundingBox())!
  expect(Math.abs(selectedBox.x - entryBox.x)).toBeLessThan(3)
  await page.getByRole('button', {name: '展开画布', exact: true}).click()
  const expandedBox = (await entry.boundingBox())!
  expect(Math.abs(expandedBox.x - selectedBox.x)).toBeLessThan(3)
  await page.getByRole('button', {name: '显示面板', exact: true}).click()

  // 2. 测试经典旧版深色 (legacy-dark)
  await page.evaluate(() => {
    localStorage.setItem('azurpilot.theme', 'legacy-dark')
  })
  await page.reload()
  await expect(page.locator('.program-editor')).toBeVisible()
  const legacyDarkBg = await page.locator('.program-workspace').evaluate(el => getComputedStyle(el).backgroundColor)
  const legacyDarkRgb = legacyDarkBg.match(/\d+/g)?.map(Number) ?? [255, 255, 255]
  expect(legacyDarkRgb[0]).toBeLessThan(80)
  await page.screenshot({path: 'test-results/scheduler-theme-legacy-dark.png'})

  // 3. 测试极简主题 (minimal)
  await page.evaluate(() => {
    localStorage.setItem('azurpilot.theme', 'minimal')
  })
  await page.reload()
  await expect(page.locator('.program-editor')).toBeVisible()
  const minimalBackdrop = await page.locator('.program-library').evaluate(el => getComputedStyle(el).backdropFilter)
  expect(minimalBackdrop).toBe('none')
  expect(await page.locator('.program-card').first().evaluate(el => getComputedStyle(el).boxShadow)).toBe('none')
  await page.screenshot({path: 'test-results/scheduler-theme-minimal.png'})

  // 4. 测试极致紧凑主题 (extreme)
  await page.evaluate(() => {
    localStorage.setItem('azurpilot.theme', 'extreme')
  })
  await page.reload()
  await expect(page.locator('.program-editor')).toBeVisible()
  const extremeBackdrop = await page.locator('.program-library').evaluate(el => getComputedStyle(el).backdropFilter)
  expect(extremeBackdrop).toBe('none')
  expect(await page.locator('.program-card').first().evaluate(el => getComputedStyle(el).borderTopLeftRadius)).toBe('0px')
  await page.screenshot({path: 'test-results/scheduler-theme-extreme.png'})

  // 5. 测试经典旧版浅色 (legacy-light)
  await page.evaluate(() => {
    localStorage.setItem('azurpilot.theme', 'legacy-light')
  })
  await page.reload()
  await expect(page.locator('.program-editor')).toBeVisible()
  await page.screenshot({path: 'test-results/scheduler-theme-legacy-light.png'})

  // 6. 切回默认浅色 (light) 并截图
  await page.evaluate(() => {
    localStorage.setItem('azurpilot.theme', 'light')
  })
  await page.reload()
  await expect(page.locator('.program-editor')).toBeVisible()
  const lightEditorBox = (await page.locator('.program-editor').boundingBox())!
  const lightTopbarBox = (await page.locator('.topbar').boundingBox())!
  expect(Math.abs(lightEditorBox.x - lightTopbarBox.x)).toBeLessThan(1)
  expect(await page.locator('.program-editor').evaluate(el => getComputedStyle(el).borderTopLeftRadius)).toBe('26px')
  await page.screenshot({path: 'test-results/scheduler-theme-light.png', fullPage: true})
})

test('调度编辑区按实际宽度切换面板，并跟随玻璃材质参数', async ({page}) => {
  await page.setViewportSize({width: 1180, height: 850})
  await page.goto('/#/i/demo-alt/task/SchedulerProgram')
  const editor = page.locator('.program-editor')
  await expect(editor).toBeVisible()
  await expect(editor).toHaveClass(/is-compact/)
  await expect(page.locator('.program-mobile-panels')).toBeVisible()
  await expect(page.locator('.program-library')).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

  await page.locator('.program-mobile-panels').getByRole('button', {name: '卡片库'}).click()
  await expect(page.locator('.program-library')).toBeVisible()
  await page.locator('.program-library').getByRole('button', {name: '读取资源', exact: true}).click()
  await expect(page.locator('.program-library')).toBeHidden()

  const glass = await page.evaluate(() => {
    const root = document.documentElement
    root.dataset.material = 'glass'
    root.style.setProperty('--theme-surface-alpha', '44%')
    root.style.setProperty('--theme-sidebar-alpha', '52%')
    const workspace = document.querySelector('.program-workspace')!
    const toolbar = document.querySelector('.program-toolbar')!
    const library = document.querySelector('.program-library')!
    return {workspace: getComputedStyle(workspace).backgroundColor, toolbar: getComputedStyle(toolbar).backgroundColor, library: getComputedStyle(library).backgroundColor}
  })
  await page.screenshot({path: 'test-results/scheduler-editor-compact-glass.png'})
  await page.locator('.program-mobile-panels').getByRole('button', {name: '卡片库'}).click()
  await expect(page.locator('.program-mobile-panels').getByRole('button', {name: '卡片库'})).toHaveClass(/active/)
  await expect(page.locator('.program-mobile-panels').getByRole('button', {name: '画布', exact: true})).not.toHaveClass(/active/)
  await expect(page.locator('.program-library')).toBeVisible()
  await page.screenshot({path: 'test-results/scheduler-editor-compact-glass-library.png'})
  await page.locator('.program-mobile-panels').getByRole('button', {name: '画布', exact: true}).click()
  const plain = await page.evaluate(() => {
    document.documentElement.dataset.material = 'plain'
    const workspace = document.querySelector('.program-workspace')!
    const toolbar = document.querySelector('.program-toolbar')!
    const library = document.querySelector('.program-library')!
    return {workspace: getComputedStyle(workspace).backgroundColor, toolbar: getComputedStyle(toolbar).backgroundColor, library: getComputedStyle(library).backgroundColor}
  })
  expect(glass.workspace).not.toBe(plain.workspace)
  expect(glass.toolbar).not.toBe(plain.toolbar)
  expect(glass.library).not.toBe(plain.library)
  await page.screenshot({path: 'test-results/scheduler-editor-compact-plain.png'})
})

test('卡片语义化图标呈现、全卡片排列与终结节点无下一步出口', async ({page}) => {
  await page.goto('/#/i/demo-main/task/SchedulerProgram')
  await expect(page.locator('.program-editor')).toBeVisible()

  // 1. 点击“全卡片排列”模板按钮并验证加载全量卡片
  await expect(page.getByRole('button', {name: '全卡片排列', exact: true})).toBeVisible()
  await page.getByRole('button', {name: '全卡片排列', exact: true}).click()
  await expect(page.locator('.react-flow__node')).toHaveCount(42)

  // 2. 验证各卡片标题内渲染了带有 aria-hidden 的专属 SVG 图标
  const icons = page.locator('.react-flow__node .program-card-icon')
  await expect(icons.first()).toBeVisible()
  expect(await icons.count()).toBeGreaterThanOrEqual(40)
  await expect(icons.first()).toHaveAttribute('aria-hidden', 'true')

  // 3. 验证终结节点（结束程序 end、结束本轮循环 loop_end）无右侧下一步出口
  const endNode = page.locator('.react-flow__node[data-id="end"]')
  await expect(endNode).toBeVisible()
  await expect(endNode.locator('.program-card-heading strong')).toHaveText('结束程序')
  // 具有执行入口（左侧 handle）
  await expect(endNode.locator('[data-handleid="control:in"]')).toBeAttached()
  // 严禁存在右侧出口（exits 容器为空或不存在）
  await expect(endNode.locator('.program-card-exits')).toHaveCount(0)

  const loopEndNode = page.locator('.react-flow__node[data-id="loop_end"]')
  await expect(loopEndNode).toBeVisible()
  await expect(loopEndNode.locator('.program-card-heading strong')).toHaveText('结束本轮循环')
  await expect(loopEndNode.locator('[data-handleid="control:in"]')).toBeAttached()
  await expect(loopEndNode.locator('.program-card-exits')).toHaveCount(0)

  // 4. 验证程序入口（entry）只有下一步出口，严禁存在左侧执行入口
  const entryNode = page.locator('.react-flow__node[data-id="entry"]')
  await expect(entryNode).toBeVisible()
  await expect(entryNode.locator('[data-handleid="control:in"]')).toHaveCount(0)
  await expect(entryNode.locator('[data-handleid="control:next"]')).toBeAttached()
  await expect(entryNode.locator('.program-card-exits')).toHaveCount(1)

  // 5. 验证卡片库侧边栏包含专属图标
  const libraryIcons = page.locator('.program-library button svg.lucide')
  expect(await libraryIcons.count()).toBeGreaterThanOrEqual(40)

  // 6. 点击选中卡片时，右侧属性面板标题展示对应图标
  await endNode.locator('.program-card-heading').click()
  await expect(page.locator('.program-properties-icon')).toBeVisible()

  // 7. 保存全卡片展示截图与重点卡片截图
  await page.screenshot({path: 'test-results/scheduler-all-cards-no-terminal-exits.png', fullPage: true})
  const compareNode = page.locator('.react-flow__node[data-id="compare"]')
  if (await compareNode.count() > 0) {
    await compareNode.screenshot({path: 'test-results/scheduler-card-compare.png'})
  }
  await page.getByRole('button', {name: '定位入口', exact: true}).click()
  await expect.poll(async () => {
    const entryBox = await entryNode.boundingBox()
    const libraryBox = await page.locator('.program-library').boundingBox()
    return entryBox && libraryBox ? entryBox.x - (libraryBox.x + libraryBox.width) : -1
  }).toBeGreaterThan(0)
})


test('主页实例状态、任务搜索收起与导航固定', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByRole('heading', {name: /好，指挥官/})).toBeVisible()
  await expect(page.locator('.home-stats')).toContainText('全部实例')
  await expect(page.locator('.instance-card').filter({hasText: 'demo-main'})).toContainText('未运行')
  await expect(page.locator('.sidebar .instance-picker')).toHaveCount(0)
  await expect(page.locator('.sidebar-footer')).toHaveCount(0)
  await expect(page.locator('a.home-deck-link')).toHaveAttribute('href', 'https://github.com/wess09/AzurPilot')
  await expect(page.locator('.primary-nav .nav-open-source')).toHaveAttribute('href', 'https://github.com/wess09/AzurPilot')
  await page.locator('.home-legacy-toggle').click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'legacy-light')
  await page.locator('.home-legacy-toggle').click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.screenshot({path: 'test-results/home-desktop.png', fullPage: true})
  await page.locator('.instance-card').filter({hasText: 'demo-main'}).click()
  await expect(page.getByRole('heading', {name: 'demo-main', exact: true})).toBeVisible()
  await expect(page.getByLabel('搜索任务', {exact: true})).toHaveCount(0)
  await page.getByRole('button', {name: '展开任务搜索'}).click()
  await page.getByLabel('搜索任务', {exact: true}).fill('Alas')
  await expect(page.locator('.task-group-button')).toHaveCount(1)
  await page.getByRole('button', {name: '收起任务搜索'}).click()
  await expect(page.getByLabel('搜索任务', {exact: true})).toHaveCount(0)
  expect(await page.locator('.task-group-button').count()).toBeGreaterThan(1)
  await page.getByRole('button', {name: '启动调度器'}).click()
  await page.getByRole('link', {name: 'AzurPilot 主页'}).click()
  await expect(page.locator('.instance-card').filter({hasText: 'demo-main'})).toContainText('运行中')
  await expect(page.locator('.instance-card').filter({hasText: 'demo-main'})).toContainText('委托')
  await page.locator('.instance-card').filter({hasText: 'demo-main'}).click()
  await page.getByRole('button', {name: '停止运行'}).click()
  await page.goto('/#/i/demo-main/task/Alas')
  await expect(page.locator('[id="Alas.Emulator.Serial"]')).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  // 顶栏吸顶：滚到底后仍贴住视口顶部且可见。
  const topbar = (await page.locator('.topbar').boundingBox())!
  expect(topbar.y).toBeLessThan(1)
  expect(topbar.y + topbar.height).toBeGreaterThan(0)
  await page.locator('.breadcrumb').getByRole('button', {name: '切换实例'}).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', {name: '切换实例'})).toBeFocused()
  expect(errors).toEqual([])
})

test('空实例主页仍可访问全局设置，系统设置不请求实例数据', async ({page}) => {
  const methods: string[] = []
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    const ids = new Set<string>()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      methods.push(request.method)
      if (request.method === 'instances.list') ids.add(request.id)
      server.send(message)
    })
    server.onMessage(message => {
      const result = JSON.parse(String(message))
      if (ids.has(result.id)) result.result = []
      if (result.topic === 'instances') result.data = []
      socket.send(JSON.stringify(result))
    })
  })
  await page.goto('/')
  await expect(page.getByRole('button', {name: '创建第一个实例'})).toBeVisible()
  await page.locator('.primary-nav').getByRole('link', {name: '系统设置'}).click()
  await expect(page.getByText('删除当前实例')).toHaveCount(0)
  await page.locator('.primary-nav').getByRole('link', {name: '界面设置'}).click()
  await expect(page.getByLabel('界面主题')).toBeVisible()
  expect(methods).not.toContain('startup.get')
  expect(methods).not.toContain('config.get')
  await page.setViewportSize({width: 390, height: 844})
  await page.goto('/')
  await page.screenshot({path: 'test-results/home-empty-mobile.png', fullPage: true})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('实例列表读取失败不阻塞全局设置', async ({page}) => {
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (request.method === 'instances.list') socket.send(JSON.stringify({v: 1, type: 'response', id: request.id, ok: false, error: {code: 'INTERNAL_ERROR', message: '测试实例读取失败'}}))
      else server.send(message)
    })
  })
  await page.goto('/#/interface')
  await expect(page.getByLabel('界面主题')).toBeVisible()
  await page.goto('/#/remote')
  await expect(page.getByLabel('监听端口')).toBeVisible()
})

test('启动开关在系统设置页保存，点名称不切换且保存后不回弹', async ({page}) => {
  await page.goto('/#/i/demo-main/task/Alas')
  const autoRun = page.getByLabel('启动时自动运行', {exact: true})
  const remember = page.getByLabel('启动时记忆运行', {exact: true})
  const before = await remember.getAttribute('aria-checked')
  await page.locator('.config-groups .field-name').nth(1).click()
  await expect(remember).toHaveAttribute('aria-checked', before!)
  await remember.check()
  await expect(page.locator('#instance-remember-status')).toHaveText('已保存')
  // 状态标记消失即队列已丢弃该条目，此后开关仍须显示服务端的值。
  await expect(page.locator('#instance-remember-status')).toHaveCount(0)
  await expect(remember).toHaveAttribute('aria-checked', 'true')
  await autoRun.check()
  await expect(page.locator('#instance-startup-status')).toHaveText('已保存')
})

test('仪表盘设置只含仪表盘项：无启动开关、无删除实例', async ({page}) => {
  await page.goto('/')
  await page.getByRole('button', {name: '新建实例'}).click()
  const name = `home_${Date.now()}`
  await page.getByLabel('实例名称').fill(name)
  await page.getByRole('dialog').getByRole('button', {name: '创建实例', exact: true}).click()
  await page.locator('.primary-nav').getByRole('link', {name: '运行总览', exact: true}).click()
  await page.getByRole('button', {name: '仪表盘设置'}).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('switch', {name: '卡片适应'})).toBeVisible()
  await expect(dialog.getByLabel('启动时自动运行', {exact: true})).toHaveCount(0)
  await expect(dialog.getByRole('button', {name: '删除实例', exact: true})).toHaveCount(0)
})

test('Logo 旁更新提示、完整提交分页、获取和应用更新', async ({page}) => {
  await page.goto('/')
  await expect(page.locator('.topbar-right').getByText('新版本可用')).toHaveCount(0)
  const updateNotice = page.locator('.sidebar-brand').getByRole('link', {name: '新版本可用'})
  await expect(updateNotice).toBeVisible()
  await expect(updateNotice).toHaveText('新')
  await updateNotice.click()
  await expect(page.getByRole('heading', {name: /^更新器/})).toBeVisible()
  await expect(page.locator('.head-card')).toHaveCount(2)
  await expect(page.locator('.commit-row')).toHaveCount(50)
  await expect(page.locator('.commit-ref')).toHaveCount(2)
  await page.getByText('展开详情', {exact: true}).click()
  await expect(page.locator('.commit-detail pre')).toContainText('统一全局设置和更新入口')
  await page.screenshot({path: 'test-results/updater-desktop.png', fullPage: true})
  await page.getByRole('button', {name: '下一页'}).click()
  await expect(page.locator('.commit-pagination')).toContainText('51–100 / 123')
  await page.getByRole('button', {name: '下一页'}).click()
  await expect(page.locator('.commit-row')).toHaveCount(23)
  await expect(page.getByRole('button', {name: '下一页'})).toBeDisabled()
  await page.getByRole('button', {name: '获取更新', exact: true}).click()
  await page.getByRole('button', {name: '更新', exact: true}).click()
  await expect(page.locator('.primary-nav .tiny-dot')).toHaveCount(0)
  await expect(page.locator('.update-summary')).toContainText('已是最新')
  await expect(page.locator('.commit-pagination')).toContainText('1–50 / 123')
  await page.setViewportSize({width: 390, height: 844})
  await page.screenshot({path: 'test-results/updater-mobile.png', fullPage: true})
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.goto('/#/interface')
  await page.getByRole('combobox', {name: '界面主题', exact: true}).click()
  await page.getByRole('option', {name: '深色', exact: true}).click()
  await page.goto('/#/updater')
  await page.screenshot({path: 'test-results/updater-dark.png'})
})

test('SHA 不匹配警告与更新确认弹窗', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  // mock 服务切到分叉场景：本地 HEAD 不在更新源历史上，模拟镜像重写历史后的 SHA 分离。
  await fetch('http://127.0.0.1:22492/__mock/updater?mode=diverged')
  await page.goto('/#/updater')
  await expect(page.locator('.mismatch-note')).toContainText('SHA 不匹配')
  await page.getByRole('button', {name: '更新', exact: true}).click()
  await expect(page.locator('.modal h2')).toHaveText('SHA 不匹配')
  await expect(page.locator('.modal')).toContainText('GitCode')
  // 取消不更新：弹窗关闭且状态保持有更新可用。
  await page.locator('.modal').getByRole('button', {name: '取消', exact: true}).click()
  await expect(page.locator('.modal')).toHaveCount(0)
  await expect(page.locator('.update-summary')).toContainText('新版本可用')
  // 确认更新：本地对齐到更新源历史，状态回到已是最新。
  await page.getByRole('button', {name: '更新', exact: true}).click()
  await page.locator('.modal').getByRole('button', {name: '仍然更新'}).click()
  await expect(page.locator('.modal')).toHaveCount(0)
  await expect(page.locator('.update-summary')).toContainText('已是最新')
  await expect(page.locator('.mismatch-note')).toHaveCount(0)
  expect(errors).toEqual([])
  await fetch('http://127.0.0.1:22492/__mock/updater?mode=default')
})

test('指挥喵评分报告面板展示、刷新与空状态', async ({page}) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/i/demo-main/task/MeowfficerScore')
  const panel = page.locator('.meow-panel')
  await expect(panel).toBeVisible()
  await expect(panel.locator('.meow-summary')).toContainText('共 2 只')
  await expect(panel).toContainText('克雷喵')
  await expect(panel.locator('.meow-card').first().locator('.meow-tier').first()).toHaveText('准毕业')
  await expect(panel).toContainText('x + y = 1 + 6.0')
  await expect(panel.locator('.meow-talent.is-special').first()).toBeVisible()
  await expect(panel.locator('.meow-talent.is-inferred').first()).toBeVisible()
  await expect(panel).toContainText('评分口径来自公开攻略')
  await expect(panel.locator('details.meow-others').first()).toBeVisible()
  // 加权点制的雷暴口径不给 x/y：不渲染公式，改用后端给的 yLabel 说明命中行。
  const weighted = panel.locator('.meow-card').nth(1)
  await expect(weighted).toContainText('雷暴猫')
  await expect(weighted).toContainText('加权命中')
  await expect(weighted.locator('.meow-formula')).toHaveCount(0)
  // 自定义 yLabel 不能折行，且要与命中标签同一基线。
  const weightedAxis = weighted.locator('.meow-axis').last()
  expect(await weightedAxis.locator('.meow-axis-label').evaluate(node => node.getClientRects().length)).toBe(1)
  expect(await weightedAxis.evaluate(node => getComputedStyle(node).alignItems)).toBe('baseline')
  // 报告面板排在参数卡**下方**、日志**上方**：先看参数与运行入口，再看结果。
  await expect(page.locator('[id="MeowfficerScore.MeowfficerScore.Source"]')).toBeVisible()
  await expect(page.locator('.config-groups')).toContainText('评分来源')
  await expect(page.getByRole('button', {name: '运行工具', exact: true})).toBeVisible()
  await expect(page.getByLabel('日志内容')).toBeVisible()
  const configBox = await page.locator('.config-groups').boundingBox()
  const panelBox = await panel.boundingBox()
  const logBox = await page.locator('.tool-log-panel').boundingBox()
  expect(panelBox!.y).toBeGreaterThan(configBox!.y)
  expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(logBox!.y + 1)
  // HTML 报告入口：有数据时给出新窗口链接。
  const reportLink = panel.getByRole('link', {name: '查看完整报告', exact: true})
  await expect(reportLink).toHaveAttribute('href', '/reports/meowfficer_score')
  await expect(reportLink).toHaveAttribute('target', '_blank')
  await panel.getByRole('button', {name: '刷新', exact: true}).click()
  await expect(panel).toContainText('克雷喵')
  await page.screenshot({path: 'test-results/meowfficer-score.png', fullPage: true, animations: 'disabled'})
  // 未跑过任务时后端返回 NOT_FOUND，页面显示空状态而不是错误，也不给报告入口（会 404）。
  await page.goto('/#/i/demo-alt/task/MeowfficerScore')
  await expect(page.locator('.meow-panel')).toContainText('还没跑过评分任务')
  await expect(page.locator('.meow-panel').getByRole('link', {name: '查看完整报告', exact: true})).toHaveCount(0)
  expect(errors).toEqual([])
})

test('日志工具条固定在表头，窄窗口下不再压住日志内容', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'light')
    localStorage.setItem('azurpilot.material', 'glass')
  })
  // 1060px 会切到紧凑布局：操作按钮进表头，是最容易把工具条挤出表头、压在日志上的场景。
  await page.setViewportSize({width: 1060, height: 720})
  await page.goto('/#/i/demo-main/overview')
  const toolbar = page.locator('.monitor-toolbar-slot .log-toolbar')
  await expect(toolbar).toBeVisible()
  await expect(page.locator('.monitor-toolbar-slot .log-toolbar .icon-button').first()).toBeVisible()
  // 工具条必须在表头内（与日志/截图切换同一行），且与日志内容零重叠。
  const geometry = await page.evaluate(() => {
    const bar = document.querySelector('.monitor-toolbar-slot .log-toolbar')!.getBoundingClientRect()
    const content = document.querySelector('.monitor-panel .log-content')!.getBoundingClientRect()
    const tabs = document.querySelector('.monitor-panel .monitor-tabs')!.getBoundingClientRect()
    return {
      overlap: Math.max(0, Math.min(bar.bottom, content.bottom) - Math.max(bar.top, content.top)),
      insideHeader: bar.top >= tabs.top - 1 && bar.bottom <= tabs.bottom + 1,
      headerOverflow: document.querySelector('.monitor-panel .monitor-tabs')!.scrollHeight - document.querySelector('.monitor-panel .monitor-tabs')!.clientHeight,
    }
  })
  expect(geometry.overlap).toBe(0)
  expect(geometry.insideHeader).toBe(true)
  expect(geometry.headerOverflow).toBeLessThanOrEqual(1)
  await page.locator('.monitor-panel').screenshot({path: 'test-results/log-toolbar.png', animations: 'disabled'})
})
