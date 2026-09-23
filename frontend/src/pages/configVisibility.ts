import type { Field, Value } from '../api/types'

export function isFieldVisible(argument: string, field: Field, value: Value) {
  if (argument === '_info' || field.display === 'hide') return false
  // 沿用旧版 put_arg_storage：空字典不生成字段，也不生成空分组或导航。
  if (field.type === 'storage' && value !== null && typeof value === 'object' && !Array.isArray(value) && !Object.keys(value).length) return false
  return true
}
