import { beforeEach, describe, expect, it } from 'vitest'
import { recordDevLogoClick, resetDevLogoClicks } from './devMode'

describe('dev mode logo click trigger', () => {
  beforeEach(() => resetDevLogoClicks())

  it('activates on the tenth consecutive click', () => {
    for (let index = 0; index < 9; index += 1) {
      expect(recordDevLogoClick(1_000 + index * 100)).toBe(false)
    }
    expect(recordDevLogoClick(1_900)).toBe(true)
  })

  it('resets the sequence when clicks are too far apart', () => {
    expect(recordDevLogoClick(1_000)).toBe(false)
    expect(recordDevLogoClick(2_000)).toBe(false)
    for (let index = 1; index < 9; index += 1) {
      expect(recordDevLogoClick(2_000 + index * 100)).toBe(false)
    }
    expect(recordDevLogoClick(2_900)).toBe(true)
  })
})
