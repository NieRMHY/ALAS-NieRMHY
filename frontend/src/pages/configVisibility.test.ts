import { expect, it } from 'vitest'
import { isFieldVisible } from './configVisibility'

it('存储空间按旧版规则隐藏空字典，保留非空状态及其中的零值', () => {
  const field = {type: 'storage', display: 'disabled', value: {}}
  expect(isFieldVisible('Storage', field, {})).toBe(false)
  expect(isFieldVisible('Storage', field, {count: 0, enabled: false})).toBe(true)
  expect(isFieldVisible('Storage', {...field, display: 'hide'}, {count: 1})).toBe(false)
  expect(isFieldVisible('NextRun', {type: 'datetime', value: ''}, '')).toBe(true)
})
