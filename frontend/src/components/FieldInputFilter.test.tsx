// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import type { ReactElement } from 'react'
import { AppContext, type AppContextValue } from '../app/context'
import { translateUi } from '../i18n'
import { FieldInput } from './FieldInput'

const context = {ui: (key, params) => translateUi('zh-CN', key, params)} as AppContextValue

const renderField = (field: ReactElement) => render(<AppContext.Provider value={context}>{field}</AppContext.Provider>)

beforeAll(() => {
  // jsdom 没有 ResizeObserver，AutoTextarea 的高度自适应在测试里不需要真实尺寸。
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

afterEach(cleanup)

describe('过滤器字段识别', () => {
  it('值里含 > 的普通文本字段仍走多行文本框', () => {
    const value = 'nohup emulator > /tmp/emulator.log 2>&1 &'
    const {container} = renderField(<FieldInput id="Alas.EmulatorInfo.RemoteStartCommand" type="textarea" label="启动命令" value={value} onChange={vi.fn()}/>)

    expect(container.querySelector('.filter-editor')).toBeNull()
    expect((container.querySelector('textarea') as HTMLTextAreaElement).value).toBe(value)
  })

  it('值里含全角箭头的普通文本字段也不会切成代码编辑器', () => {
    const value = 'provider: ＞ null'
    const {container} = renderField(<FieldInput id="Alas.Error.OnePushConfig" type="textarea" label="推送配置" value={value} onChange={vi.fn()}/>)

    expect(container.querySelector('.filter-editor')).toBeNull()
    expect((container.querySelector('textarea') as HTMLTextAreaElement).value).toBe(value)
  })

  it('以 Filter 结尾的字段即使还没有箭头也使用高亮编辑器，并且可编辑', async () => {
    const {container} = renderField(<FieldInput id="Tactical.Tactical.TacticalFilter" type="textarea" label="战术过滤器" value="SameT4" onChange={vi.fn()}/>)

    await waitFor(() => expect(container.querySelector('.filter-editor')).not.toBeNull())
    const content = container.querySelector('.cm-content') as HTMLElement
    expect(content.getAttribute('contenteditable')).toBe('true')
    expect(content.textContent).toContain('SameT4')

    fireEvent.keyDown(content, {key: 'Enter', code: 'Enter', keyCode: 13})
    expect([...container.querySelectorAll('.cm-line')].length).toBe(2)
  })

  it('task_priority 类型的优先级字段同样使用高亮编辑器', async () => {
    const {container} = renderField(<FieldInput id="OpsiScheduling.OpsiScheduling.TaskPriorityAdjustment" type="task_priority" label="优先级调整" value="OpsiStronghold > OpsiObscure" onChange={vi.fn()}/>)

    await waitFor(() => expect(container.querySelector('.filter-editor')).not.toBeNull())
    expect((container.querySelector('.cm-content') as HTMLElement).getAttribute('contenteditable')).toBe('true')
  })

  it('参数名只是以 Filter 开头时不误判为过滤器字段', () => {
    const {container} = renderField(<FieldInput id="General.Enhance.FilterValueFloor" type="number" label="过滤下限" value={0.6} onChange={vi.fn()}/>)

    expect(container.querySelector('.filter-editor')).toBeNull()
    expect(container.querySelector('input')).not.toBeNull()
  })
})
