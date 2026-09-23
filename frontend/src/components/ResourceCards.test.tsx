import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import type { Resource } from '../api/types'
import { translateUi } from '../i18n'
import { setDashboardPref } from '../app/dashboardPrefs'
import { moveResourceKey, ResourceCards } from './ResourceCards'

function renderResources(resources: Resource[], selected = ['ActionPoint']) {
  return renderToStaticMarkup(
    <AppContext.Provider value={{ui: (key, params) => translateUi('zh-CN', key, params)} as AppContextValue}>
      <ResourceCards resources={resources} selected={selected}/>
    </AppContext.Provider>,
  )
}

describe('资源卡片', () => {
  it('按拖动目标重排卡片且不修改原数组', () => {
    const original = ['Oil', 'Coin', 'Gem', 'Cube']

    expect(moveResourceKey(original, 'Cube', 'Coin')).toEqual(['Oil', 'Cube', 'Coin', 'Gem'])
    expect(moveResourceKey(original, 'Oil', 'Cube')).toEqual(['Coin', 'Gem', 'Cube', 'Oil'])
    expect(moveResourceKey(original, 'Oil', 'Oil')).toBe(original)
    expect(original).toEqual(['Oil', 'Coin', 'Gem', 'Cube'])
  })

  it('记录时间当日只给时分秒，跨日给月日与小时', () => {
    const pad = (count: number) => String(count).padStart(2, '0')
    const stamp = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    const now = new Date()
    const today = renderResources([{name: 'Oil', label: '石油', value: 1, record: stamp(now)}], ['Oil'])
    const earlier = renderResources([{name: 'Oil', label: '石油', value: 1, record: stamp(new Date(now.getTime() - 24 * 60 * 60 * 1000))}], ['Oil'])

    expect(today).toMatch(/class="resource-foot">\d{2}:\d{2}:\d{2}</)
    expect(earlier).toMatch(/class="resource-foot">\d{2}-\d{2}-\d{2}</)
  })

  it('记录时间超过一年只提示过久', () => {
    const long = new Date(Date.now() - 400 * 24 * 60 * 60 * 1000)
    const html = renderResources([{name: 'Oil', label: '石油', value: 1, record: long.toISOString()}], ['Oil'])

    expect(html).toContain('时间太久了啦…')
  })

  it('行动力与石油一致，以小字后缀显示总量', () => {
    const html = renderResources([{name: 'ActionPoint', label: '行动力', value: 101, total: 1301, record: '2026-09-16 12:00:00'}])

    expect(html).toContain('<span>行动力</span>')
    expect(html).toContain('<span>101</span><small>/ 1,301</small>')
  })

  it.each([101, 0])('总行动力与当前行动力相等时仍显示完整数值：%s', value => {
    const html = renderResources([{name: 'ActionPoint', label: '行动力', value, total: value, record: '2026-09-16 12:00:00'}])

    expect(html).toContain(`<span>${value}</span><small>/ ${value}</small>`)
  })

  it.each([undefined, 0, 100, NaN, Infinity])('总行动力缺失或异常时回退到当前行动力：%s', total => {
    const html = renderResources([{name: 'ActionPoint', label: '行动力', value: 101, total, record: '2026-09-16 12:00:00'}])

    expect(html).toContain('<span>行动力</span>')
    expect(html).toContain('<span>101</span>')
    expect(html).not.toContain('总行动力')
  })

  it.each([undefined, '2020-01-01 00:00:00'])('尚未同步时不展示总量和明细：%s', record => {
    const html = renderResources([{name: 'ActionPoint', label: '行动力', value: 101, total: 1301, record}])

    expect(html).toContain('<span>—</span>')
    expect(html).not.toContain('1,301')
    expect(html).not.toContain('<small>')
  })

  it('其他资源仍显示当前值和上限', () => {
    const html = renderResources([{name: 'Oil', label: '石油', value: 1000, limit: 16000, record: '2026-09-16 12:00:00'}], ['Oil'])

    expect(html).toContain('<span>1,000</span>')
    expect(html).toContain('<small>/ 16,000</small>')
  })

  it('总行动力优先时两个数字互换', () => {
    setDashboardPref('totalFirst', true)
    try {
      const html = renderResources([{name: 'ActionPoint', label: '行动力', value: 101, total: 1301, record: '2026-09-16 12:00:00'}])

      expect(html).toContain('<span>1,301</span><small>/ 101</small>')
    } finally {
      setDashboardPref('totalFirst', false)
    }
  })

  it('通用卡片把已选资源收进同一个容器', () => {
    setDashboardPref('merged', true)
    try {
      const html = renderResources([{name: 'Oil', label: '石油', value: 1000, record: '2026-09-16 12:00:00'}], ['Oil', 'Coin'])

      expect(html.match(/class="resource-card resource-merged"/g)).toHaveLength(1)
      expect(html.match(/resource-merged-item/g)).toHaveLength(2)
      expect(html.match(/class="resource-heading"/g)).toHaveLength(2)
      expect(html.match(/class="resource-value-content"/g)).toHaveLength(2)
    } finally {
      setDashboardPref('merged', false)
    }
  })
})
