import { beforeEach, describe, expect, it } from 'vitest'
import { motionReducedActive, readMotionPrefs, resetMotionPrefs, setMotionReduced, setMotionSpeed, setMotionStrength, subscribeMotionPrefs } from './motionPrefs'

describe('motionPrefs（动效调试台偏好）', () => {
  beforeEach(() => resetMotionPrefs())

  it('默认值：速度 0.5×、增强力度、未开启减少模拟', () => {
    expect(readMotionPrefs()).toEqual({speed: 2, strength: 'strong', reduced: false})
  })

  it('可切换并通知订阅者；退订后不再通知', () => {
    let calls = 0
    const unsubscribe = subscribeMotionPrefs(() => { calls += 1 })
    setMotionSpeed(4)
    setMotionStrength('standard')
    setMotionReduced(true)
    unsubscribe()
    setMotionSpeed(1)
    expect(calls).toBe(3)
    expect(readMotionPrefs()).toEqual({speed: 1, strength: 'standard', reduced: true})
  })

  it('无 DOM 环境（node/SSR）下按「减少」处理且加载与切换均不抛错', () => {
    // 模块在 node 环境导入时不应触碰 document；此用例能跑通即证明守卫有效。
    expect(motionReducedActive()).toBe(true)
    setMotionSpeed(4)
    expect(readMotionPrefs().speed).toBe(4)
  })
})
