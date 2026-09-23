import { describe, expect, it } from 'vitest'
import { canApplyRestrictedLua, diagnosticLocation, diagnosticSeverity, validationFromError } from './restrictedLuaState'

describe('受限 Lua 草稿状态', () => {
  const valid = {valid: true, diagnostics: []}

  it('只有当前草稿检查通过后才能应用，后续编辑会立即失效', () => {
    const checked = {draft: 'return true', checkedScript: 'return true', validation: valid, checking: false, applying: false}
    expect(canApplyRestrictedLua(checked)).toBe(true)
    expect(canApplyRestrictedLua({...checked, draft: 'return false'})).toBe(false)
    expect(canApplyRestrictedLua({...checked, checking: true})).toBe(false)
    expect(canApplyRestrictedLua(checked, true)).toBe(false)
  })

  it('保留服务端 1 基行列诊断并为未标注的失败诊断提供错误级别', () => {
    const diagnostic = {message: '不允许调用 os.execute', line: 3, column: 8}
    expect(diagnosticLocation(diagnostic)).toBe('3:8')
    expect(diagnosticSeverity(diagnostic, false)).toBe('error')
    expect(diagnosticSeverity({...diagnostic, severity: 'warning'}, false)).toBe('warning')
  })

  it('从校验失败的 API 详情中恢复行列诊断', () => {
    expect(validationFromError({
      code: 'INVALID_PARAMS', message: '高级商店策略脚本无效',
      details: [{code: 'CALL_FORBIDDEN', message: '不允许调用 os.execute', line: 4, column: 12}],
    })).toEqual({
      valid: false, summary: '高级商店策略脚本无效',
      diagnostics: [{code: 'CALL_FORBIDDEN', message: '不允许调用 os.execute', line: 4, column: 12, severity: undefined}],
    })
  })
})
