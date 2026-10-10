/**
 * @fileoverview 启动器卡片状态行文案测试：状态机 + 后端字段 → 界面用语。
 */
import { describe, expect, it } from 'vitest'
import { launcherStatusText, type Phase } from './LauncherCard'

/** 取词即回显键名，断言直接对准用到的 GUI 键。 */
const t = (key: string) => key

function text(phase: Phase, state: Partial<{enabled: boolean; pending: boolean; detail: string}> = {}) {
  return launcherStatusText(phase, {enabled: false, pending: false, detail: '', ...state}, t)
}

describe('启动器卡片状态行', () => {
  it('本机读取中与未连接各有专门文案', () => {
    expect(text('loading')).toBe('Gui.Launcher.Loading')
    expect(text('disconnected')).toBe('Gui.Launcher.Disconnected')
  })

  it('远端访问、平台不支持与设置中沿用既有提示', () => {
    expect(text('remote')).toBe('Gui.Launcher.RemoteUnavailable')
    expect(text('unsupported')).toBe('Gui.Launcher.Unsupported')
    expect(text('setting')).toBe('Gui.Launcher.Setting')
  })

  it('失败时附带原因', () => {
    expect(text('failed', {detail: '启动器未连接，请通过启动器打开 AzurPilot'}))
      .toBe('Gui.Launcher.Failed：启动器未连接，请通过启动器打开 AzurPilot')
  })

  it('已连接时区分「状态未知」「已开启」「已关闭」', () => {
    expect(text('ready', {pending: true})).toBe('Gui.Launcher.Connected · Gui.Launcher.Loading')
    expect(text('ready', {enabled: true})).toBe('Gui.Launcher.Connected · Gui.Launcher.Enabled')
    expect(text('ready')).toBe('Gui.Launcher.Connected · Gui.Launcher.Disabled')
  })
})
