// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { AppContext, type AppContextValue } from '../app/context'
import { translateUi } from '../i18n'
import { FleetInfo } from './FleetInfoPage'

function info(value: unknown) {
  return render(<AppContext.Provider value={{
    ui: (key, params) => translateUi('zh-CN', key, params),
  } as AppContextValue}><FleetInfo value={value}/></AppContext.Provider>)
}

afterEach(cleanup)

describe('舰队信息心情兼容性', () => {
  it('显示名称等级和心情，零值有效，缺失或越界为未知', () => {
    info({vanguard: {1: [
      {name: '甲', level: 125, emotion: 150}, {name: '乙', level: 100, emotion: 0},
      {name: '丙', level: 70, emotion: null}, {name: '丁', level: 10, emotion: 151},
    ]}})
    expect(screen.getByText('甲')).toBeTruthy()
    expect(screen.getByText('Lv.125 · 心情 150')).toBeTruthy()
    expect(screen.getByText('Lv.100 · 心情 0')).toBeTruthy()
    expect(screen.getByText('Lv.70 · 心情 未知')).toBeTruthy()
    expect(screen.getByText('Lv.10 · 心情 未知')).toBeTruthy()
  })

  it('兼容旧字符串舰船与旧对象、JSON 字符串', () => {
    info(JSON.stringify({main: {1: ['旧舰船', {name: '旧对象', level: 125}]}}))
    expect(screen.getByText('旧舰船')).toBeTruthy()
    expect(screen.getByText('旧对象')).toBeTruthy()
    expect(screen.getByText('Lv.125 · 心情 未知')).toBeTruthy()
  })

  it('显示实际舰位，旧记录不按数组位置推断舰位', () => {
    info({vanguard: {1: [{name: '花月', slot: 5, level: 105}, {name: '旧对象'}]}})
    expect(screen.getByText('舰位 5 · 花月')).toBeTruthy()
    expect(screen.queryByText(new RegExp('舰位 4'))).toBeNull()
    expect(screen.queryByText(new RegExp('舰位 6'))).toBeNull()
  })
})
