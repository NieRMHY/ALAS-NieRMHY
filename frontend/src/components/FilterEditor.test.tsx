// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'
import { FilterEditor } from './FilterEditor'

/* 编辑器内容按行读回：CodeMirror 把文档拆成 .cm-line，换行不在 textContent 里。 */
function docLines(container: HTMLElement) {
  return [...container.querySelectorAll('.cm-line')].map(node => node.textContent ?? '').join('\n')
}

function pressEnter(content: HTMLElement) {
  fireEvent.keyDown(content, {key: 'Enter', code: 'Enter', keyCode: 13})
}

function mount(value: string, options: {disabled?: boolean; onChange?: (next: string) => void} = {}) {
  const onChange = options.onChange ?? vi.fn()
  const result = render(
    <FilterEditor id="Tactical.Tactical.TacticalFilter" label="战术过滤器" value={value} disabled={options.disabled} onChange={onChange}/>,
  )
  const content = result.container.querySelector('.cm-content') as HTMLElement
  return {...result, content, onChange}
}

afterEach(cleanup)

describe('过滤器编辑器草稿同步', () => {
  it('外部轮询更新不覆盖未提交的草稿', () => {
    const {container, content, onChange, rerender} = mount('SameT4 > RedT3')
    pressEnter(content)
    expect(docLines(container)).toBe('\nSameT4 > RedT3')

    // 轮询把服务器上的旧值写回 props：正在输入的内容不能被换掉。
    rerender(<FilterEditor id="Tactical.Tactical.TacticalFilter" label="战术过滤器" value="BlueT2" onChange={onChange}/>)
    expect(docLines(container)).toBe('\nSameT4 > RedT3')

    fireEvent.blur(content)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith('\nSameT4 > RedT3')
  })

  it('键入期间不提交，失焦才写回配置', () => {
    const {content, onChange} = mount('A1 > A2')
    pressEnter(content)
    expect(onChange).not.toHaveBeenCalled()

    fireEvent.blur(content)
    expect(onChange).toHaveBeenCalledWith('\nA1 > A2')
  })

  it('提交值回显后继续跟随外部更新', () => {
    const {container, content, onChange, rerender} = mount('A1')
    pressEnter(content)
    fireEvent.blur(content)
    expect(onChange).toHaveBeenLastCalledWith('\nA1')

    // 父组件确认保存后把提交值回显下来：草稿转为已保存，不应再次触发提交。
    rerender(<FilterEditor id="Tactical.Tactical.TacticalFilter" label="战术过滤器" value={'\nA1'} onChange={onChange}/>)
    expect(docLines(container)).toBe('\nA1')

    // 回显之后的普通外部更新照常同步。
    rerender(<FilterEditor id="Tactical.Tactical.TacticalFilter" label="战术过滤器" value="B1 > B2" onChange={onChange}/>)
    expect(docLines(container)).toBe('B1 > B2')
  })

  it('没有草稿时普通外部更新直接同步', () => {
    const {container, onChange, rerender} = mount('A1')
    rerender(<FilterEditor id="Tactical.Tactical.TacticalFilter" label="战术过滤器" value="C1" onChange={onChange}/>)
    expect(docLines(container)).toBe('C1')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('卸载时提交未保存的草稿', () => {
    const onChange = vi.fn()
    const {content, unmount} = mount('A1', {onChange})
    pressEnter(content)
    unmount()
    expect(onChange).toHaveBeenCalledWith('\nA1')
  })

  it('只读字段不可编辑，失焦不提交，外部值仍然同步', () => {
    const {container, content, onChange, rerender} = mount('A1', {disabled: true})
    expect(content.getAttribute('contenteditable')).toBe('false')
    expect(content.getAttribute('aria-disabled')).toBe('true')
    expect(container.querySelector('.filter-editor')?.classList.contains('is-disabled')).toBe(true)

    fireEvent.blur(content)
    expect(onChange).not.toHaveBeenCalled()

    rerender(<FilterEditor id="Tactical.Tactical.TacticalFilter" label="战术过滤器" value="D1" disabled onChange={onChange}/>)
    expect(docLines(container)).toBe('D1')
  })

  it('标签变化只重配置无障碍属性，不重建编辑器丢草稿', () => {
    const {container, content, onChange, rerender} = mount('A1')
    pressEnter(content)

    rerender(<FilterEditor id="Tactical.Tactical.TacticalFilter" label="战术学院过滤器" value="A1" onChange={onChange}/>)
    expect(docLines(container)).toBe('\nA1')
    expect(content.getAttribute('aria-label')).toBe('战术学院过滤器')
    expect(content.getAttribute('role')).toBe('textbox')
  })
})
