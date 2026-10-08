import { expect, test } from '@playwright/test'

test('舰队信息兼容旧记录并展示心情与未知值', async ({page}) => {
  const requests = new Map<string, string>()
  await page.routeWebSocket('**/api/v1/ws', socket => {
    const server = socket.connectToServer()
    socket.onMessage(message => {
      const request = JSON.parse(String(message))
      requests.set(request.id, request.method)
      server.send(message)
    })
    server.onMessage(message => {
      const response = JSON.parse(String(message))
      if (response.ok && requests.get(response.id) === 'config.get') {
        response.result.values.FleetInfo = {FleetInfo: {Result: {
          vanguard: {1: [{name: '测试先锋', level: 125, emotion: 150}, {name: '测试零心情', level: 100, emotion: 0}]},
          main: {1: [{name: '测试未知', level: 70, emotion: null}, {name: '旧对象', level: 10}]},
          submarine: {1: ['旧字符串']},
        }}}
      }
      socket.send(JSON.stringify(response))
    })
  })
  await page.goto('/#/i/testpilot/task/FleetInfo')
  const fleet = page.locator('.fleet-grid .panel').first()
  await expect(fleet).toContainText('测试先锋')
  await expect(fleet).toContainText('Lv.125 · 心情 150')
  await expect(fleet).toContainText('Lv.100 · 心情 0')
  await expect(fleet).toContainText('Lv.70 · 心情 未知')
  await expect(fleet).toContainText('Lv.10 · 心情 未知')
  await expect(fleet).toContainText('旧字符串')
  await page.setViewportSize({width: 390, height: 844})
  await expect(fleet).toContainText('心情 150')
  const overflow = await page.locator('.fleet-grid').evaluate(element => element.scrollWidth > element.clientWidth)
  expect(overflow).toBe(false)
})
