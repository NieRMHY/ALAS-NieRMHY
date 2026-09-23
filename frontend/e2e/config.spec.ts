import { expect, test } from '@playwright/test'

const serialSelector = '[id="Alas.Emulator.Serial"]'

test('两个页面的旧快照均能保存，字段更新互不覆盖', async ({page, context}) => {
  const second = await context.newPage()
  await page.goto('/#/i/testpilot/task/Alas')
  await second.goto('/#/i/testpilot/task/Alas')
  await expect(page.locator(serialSelector)).toBeVisible()
  const threshold = second.locator('[id="Alas.Error.GameStuckThreshold"]')
  await expect(threshold).toBeVisible()
  await page.locator(serialSelector).fill('parallel-page-edit')
  // “已保存”提示会延迟出现并自动消失，不能把瞬时 UI 当作提交屏障；
  // 从另一页面重新读取服务端快照，才能真正证明旧快照的字段已经合并保存。
  await expect.poll(async () => {
    await second.reload()
    return second.locator(serialSelector).inputValue()
  }).toBe('parallel-page-edit')
  await threshold.fill('7')
  await expect.poll(async () => {
    await page.reload()
    return page.locator('[id="Alas.Error.GameStuckThreshold"]').inputValue()
  }).toBe('7')
  await expect(second.locator(serialSelector)).toHaveValue('parallel-page-edit')
  await expect(page.locator('[id="Alas.Error.GameStuckThreshold"]')).toHaveValue('7')
})

test('旧响应延迟期间连续输入并切页，最终值继续保存', async ({page}) => {
  let release: (() => void) | undefined
  let firstId: string | undefined
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      if (!firstId && request.method === 'config.patch') firstId = request.id
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      if (firstId && response.id === firstId) release = () => socket.send(message)
      else socket.send(message)
    })
  })
  await page.goto('/#/i/testpilot/task/Alas')
  const serial = page.locator(serialSelector)
  await serial.fill('first-in-flight')
  await expect.poll(() => !!release).toBe(true)
  await serial.fill('latest-user-input')
  await expect(serial).toHaveValue('latest-user-input')
  await page.locator('.breadcrumb .instance-caption').click()
  release!()
  await page.goto('/#/i/testpilot/task/Alas')
  await expect(serial).toHaveValue('latest-user-input')
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.reload()
  await expect(serial).toHaveValue('latest-user-input')
})

test('请求尚未送达就断线并刷新，恢复后自动保存原输入', async ({page}) => {
  let drop = true
  let dropped = false
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      if (JSON.parse(String(message)).method === 'config.patch' && drop) {
        dropped = true
        void socket.close({code: 1012})
      } else server.send(message)
    })
  })
  await page.goto('/#/i/testpilot/task/Alas')
  const serial = page.locator(serialSelector)
  await serial.fill('survives-disconnect-and-reload')
  await expect.poll(() => dropped).toBe(true)
  drop = false
  await page.reload()
  await expect(serial).toHaveValue('survives-disconnect-and-reload')
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.reload()
  await expect(serial).toHaveValue('survives-disconnect-and-reload')
})

test('非法数字、日期和 YAML 保留草稿，其他字段仍即时保存', async ({page}) => {
  await page.goto('/#/i/testpilot/task/Alas')
  const threshold = page.locator('[id="Alas.Error.GameStuckThreshold"]')
  await threshold.fill('-')
  await expect(threshold).toHaveValue('-')
  await expect(threshold).toHaveAttribute('aria-invalid', 'true')
  const yaml = page.locator('[id="Alas.Error.OnePushConfig"]')
  await yaml.fill('provider: [')
  await expect(page.locator('[id="Alas.Error.OnePushConfig-status"]')).toContainText('YAML 格式不正确')
  await page.locator(serialSelector).fill('valid-despite-invalid-fields')
  await expect(page.locator(serialStatus)).toHaveText('已保存')
  await page.reload()
  await expect(threshold).toHaveValue('-')
  await expect(yaml).toHaveText('provider: [')
  await expect(page.locator(serialSelector)).toHaveValue('valid-despite-invalid-fields')
  await threshold.fill('3')
  await yaml.fill('provider: null')
  await expect(page.locator('[id="Alas.Error.GameStuckThreshold-status"]')).toHaveText('已保存')
  await expect(page.locator('[id="Alas.Error.OnePushConfig-status"]')).toHaveText('已保存')
  await page.goto('/#/i/testpilot/task/Main')
  const date = page.locator('[id="Main.Scheduler.NextRun"]')
  await date.fill('2026-02-30 12:00:00')
  await expect(page.locator('[id="Main.Scheduler.NextRun-status"]')).toContainText('日期格式')
  await expect(date).toHaveValue('2026-02-30 12:00:00')
  await date.fill('2099-01-01 12:00:00')
  await expect(page.locator('[id="Main.Scheduler.NextRun-status"]')).toHaveText('已保存')
  // 清空时间要回落到参数默认值：它落在过去，调度器下一轮就把任务当作待运行。
  await date.fill('')
  await expect(date).toHaveValue('2020-01-01 00:00:00')
  await expect(page.locator('[id="Main.Scheduler.NextRun-status"]')).toHaveText('已保存')
  await page.reload()
  await expect(date).toHaveValue('2020-01-01 00:00:00')
})

test('遗留的空时间草稿在恢复时被丢弃，字段回到配置里的值', async ({page}) => {
  // 旧版本拒绝空时间后把空值留在草稿里：字段已空时再清空不会触发输入事件，
  // 草稿永远换不掉。恢复草稿时丢弃它，字段回到配置里的值。
  await page.addInitScript(() => sessionStorage.setItem('azurpilot.edits.config:testpilot', JSON.stringify({
    'Main.Scheduler.NextRun': {
      value: '', payload: '', sequence: 1, status: 'error', retryable: false,
      error: '日期格式应为 YYYY-MM-DD HH:mm:ss：Main.Scheduler.NextRun',
    },
  })))
  await page.goto('/#/i/testpilot/task/Main')
  await expect(page.locator('[id="Main.Scheduler.NextRun"]')).toHaveValue('2020-01-01 00:00:00')
  await expect(page.locator('[id="Main.Scheduler.NextRun-status"]')).toHaveCount(0)
})

test('立刻运行按钮把调度时间改成可立即运行', async ({page}) => {
  await page.goto('/#/i/testpilot/task/Main')
  const date = page.locator('[id="Main.Scheduler.NextRun"]')
  const status = page.locator('[id="Main.Scheduler.NextRun-status"]')
  await date.fill('2099-01-01 12:00:00')
  await expect(status).toHaveText('已保存')
  // 按钮等同清空该字段：提交参数默认值，它落在过去，调度器下一轮即运行。
  await page.getByRole('button', {name: '立刻运行', exact: true}).click()
  await expect(date).toHaveValue('2020-01-01 00:00:00')
  await expect(status).toHaveText('已保存')
  await page.reload()
  await expect(date).toHaveValue('2020-01-01 00:00:00')
})

test('清空数字字段回落到参数默认值，不再提示格式错误', async ({page}) => {
  await page.goto('/#/i/testpilot/task/Main')
  const value = page.locator('[id="Main.Emotion.Fleet1Value"]')
  const status = page.locator('[id="Main.Emotion.Fleet1Value-status"]')
  await value.fill('95')
  await expect(status).toHaveText('已保存')
  await value.fill('')
  await expect(value).toHaveValue('119')
  await expect(status).toHaveText('已保存')
  await page.reload()
  await expect(value).toHaveValue('119')
})
