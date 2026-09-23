import { afterEach, describe, expect, it, vi } from 'vitest'
import { animateScrollTop, easeOutCubic, scrollTargetTop } from './scroll'

afterEach(() => vi.unstubAllGlobals())

describe('easeOutCubic', () => {
  it('端点精确、前段快后段慢', () => {
    expect(easeOutCubic(0)).toBe(0)
    expect(easeOutCubic(1)).toBe(1)
    expect(easeOutCubic(0.5)).toBeGreaterThan(0.5)
    expect(easeOutCubic(0.5)).toBeCloseTo(0.875, 3)
  })
})

describe('scrollTargetTop', () => {
  it('含 scroll-margin-top', () => {
    expect(scrollTargetTop(0, 0, 500, 85, 2000)).toBe(415)
  })
  it('夹取上下边界', () => {
    expect(scrollTargetTop(0, 0, 50, 85, 2000)).toBe(0)
    expect(scrollTargetTop(0, 0, 5000, 0, 2000)).toBe(2000)
    expect(scrollTargetTop(1200, 0, 300, 0, 2000)).toBe(1500)
  })
  it('容器不可滚动时归零', () => {
    expect(scrollTargetTop(0, 0, 500, 0, -50)).toBe(0)
  })
})

describe('animateScrollTop', () => {
  it('同一容器开始新滚动时取消上一帧任务', () => {
    let nextFrame = 1
    const cancelled: number[] = []
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => nextFrame++))
    vi.stubGlobal('cancelAnimationFrame', vi.fn((frame: number) => cancelled.push(frame)))
    const container = Object.assign(new EventTarget(), {scrollTop: 0}) as HTMLElement

    animateScrollTop(container, 100, 280)
    animateScrollTop(container, 200, 280)

    expect(cancelled).toEqual([1])
  })
})
