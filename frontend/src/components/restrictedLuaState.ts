import type { ScriptDiagnostic, ShopStrategyValidation } from '../api/types'

export interface RestrictedLuaState {
  draft: string
  checkedScript?: string
  validation?: ShopStrategyValidation
  checking: boolean
  applying: boolean
}

/** 只有当前草稿已通过服务端检查时，才允许将其写回配置。 */
export function canApplyRestrictedLua(state: RestrictedLuaState, disabled = false) {
  return !disabled
    && !state.checking
    && !state.applying
    && state.checkedScript === state.draft
    && state.validation?.valid === true
}

/** 服务端未标注级别时，失败结果默认按错误展示，成功结果中的诊断按警告展示。 */
export function diagnosticSeverity(diagnostic: ScriptDiagnostic, valid: boolean) {
  return diagnostic.severity ?? (valid ? 'warning' : 'error')
}

export function diagnosticLocation(diagnostic: ScriptDiagnostic) {
  if (diagnostic.line == null) return ''
  return diagnostic.column == null ? String(diagnostic.line) : `${diagnostic.line}:${diagnostic.column}`
}

/** 将 API 错误详情收敛为可显示诊断，兼容校验接口返回错误包络的实现。 */
export function validationFromError(error: unknown): ShopStrategyValidation | undefined {
  if (!error || typeof error !== 'object') return undefined
  const value = error as {code?: unknown; message?: unknown; details?: unknown}
  if (value.code !== 'INVALID_PARAMS' || !Array.isArray(value.details)) return undefined
  const diagnostics = value.details.flatMap(detail => {
    if (!detail || typeof detail !== 'object' || typeof (detail as {message?: unknown}).message !== 'string') return []
    const item = detail as {code?: unknown; message: string; line?: unknown; column?: unknown; severity?: unknown}
    return [{
      code: typeof item.code === 'string' ? item.code : undefined,
      message: item.message,
      line: typeof item.line === 'number' ? item.line : undefined,
      column: typeof item.column === 'number' ? item.column : undefined,
      severity: item.severity === 'warning' || item.severity === 'error' ? item.severity : undefined,
    } satisfies ScriptDiagnostic]
  })
  return {valid: false, diagnostics, summary: typeof value.message === 'string' ? value.message : undefined}
}
