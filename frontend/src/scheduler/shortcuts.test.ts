import {describe, expect, it} from 'vitest'
import {editorCommand} from './shortcuts'
import {compatiblePorts, portColors} from './appearance'

describe('调度画布快捷键与类型颜色', () => {
  const key = (key:string, modifiers = {}) => ({key,ctrlKey:false,metaKey:false,shiftKey:false,altKey:false,...modifiers})
  it('支持 Windows 和 macOS 的编辑操作以及退格删除', () => {
    for (const modifier of [{ctrlKey:true},{metaKey:true}]) {
      for (const [letter,command] of Object.entries({c:'copy',v:'paste',x:'cut',a:'all',z:'undo',y:'redo'})) expect(editorCommand(key(letter,modifier))).toBe(command)
      expect(editorCommand(key('Z',{...modifier,shiftKey:true}))).toBe('redo')
    }
    expect(editorCommand(key('Backspace'))).toBe('delete')
    expect(editorCommand(key('Delete'))).toBe('delete')
    expect(editorCommand(key('Escape'))).toBe('clear')
    expect(editorCommand(key('c'))).toBeUndefined()
    expect(editorCommand(key('c',{ctrlKey:true,altKey:true}))).toBeUndefined()
  })
  it('具体类型的颜色与双向兼容规则完全对应，任意值使用单独的彩环', () => {
    const types = Object.keys(portColors).filter(type => type !== 'any') as Array<keyof typeof portColors>
    for (const source of types) for (const target of types) expect(compatiblePorts(source,target), `${source} → ${target}`).toBe(portColors[source] === portColors[target])
    expect(portColors.number).toBe(portColors.duration)
    expect(portColors.number).not.toBe(portColors.boolean)
    expect(portColors.time).not.toBe(portColors.duration)
  })
})
