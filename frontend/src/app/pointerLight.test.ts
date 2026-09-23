import { describe, expect, it } from 'vitest'
import { pointerFraction } from './pointerLight'

describe('pointerFraction', () => {
  it('按目标元素自身坐标计算指针位置', () => {
    expect(pointerFraction(350, 200, 600)).toBeCloseTo(0.25)
    expect(pointerFraction(500, 20, 60)).toBe(1)
    expect(pointerFraction(0, 20, 60)).toBe(0)
  })

  it('元素尺寸无效时回退到中心', () => {
    expect(pointerFraction(100, 20, 0)).toBe(0.5)
  })
})
